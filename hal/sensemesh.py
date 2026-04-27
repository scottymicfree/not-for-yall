"""
SOVEREIGN v2.1 — SenseMesh Hardware Sensor Monitor
====================================================
Polls the I3C/I2C sensor network (TMP112 thermal diodes,
INA3221 voltage/current shunt monitors) via the OpenBMC
sideband channel that bypasses the Host OS entirely.

Hardware:
  - TI INA3221  : 3-channel voltage + current monitor (SMBus)
  - TI TMP112   : High-precision digital temperature sensor (I2C)
  - ASPEED AST2600 BMC : sensor aggregator (IPMI/Redfish)
  - I3C bus @ 12.5 MHz : primary sensor polling path (bypasses host)

In SIM mode: all readings are synthetic with realistic noise.
In PROTO/NATIVE: reads via /sys/bus/i2c/devices/ or IPMI SDR.
"""

from __future__ import annotations

import os
import time
import json
import random
import struct
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, List, Callable

from .sovereign_hal import HALSubsystem, HALMode, SubsystemHealth, HALEventBus

log = logging.getLogger("lucy.hal.sensemesh")


@dataclass
class SensorReading:
    sensor_id:   str
    label:       str
    value:       float
    unit:        str      # "C" | "V" | "mA" | "W" | "RPM"
    timestamp:   str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    alert_level: str = "ok"   # "ok" | "warning" | "critical"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SensorSnapshot:
    """Full point-in-time snapshot of all sensors."""
    timestamp:    str
    temperatures: Dict[str, float]   # label → °C
    voltages:     Dict[str, float]   # label → V
    currents:     Dict[str, float]   # label → mA
    powers:       Dict[str, float]   # label → W
    alerts:       List[str]

    def to_dict(self) -> dict:
        return asdict(self)


class SenseMeshMonitor(HALSubsystem):
    """
    Continuous hardware sensor polling with alerting.
    Runs a background thread at configurable interval (default 100ms).
    Publishes HAL_ALERT events on threshold breach.
    """

    def __init__(self, config: dict, mode: HALMode, events: HALEventBus):
        super().__init__("SenseMesh", config, mode)
        self.events   = events
        self._readings: Dict[str, SensorReading] = {}
        self._history: List[SensorSnapshot] = []   # ring buffer, max 600
        self._poll_thread: Optional[threading.Thread] = None
        self._active  = False
        self._poll_ms = config.get("polling_interval_ms", 100)
        self._thresholds = config.get("alert_thresholds", {
            "temp_critical_c": 85,
            "temp_warning_c": 75,
            "power_critical_w": 2400,
            "power_warning_w": 2200,
            "voltage_drop_mv": 50,
        })
        self._i2c_buses = config.get("i2c_buses", [])

    def init(self) -> bool:
        if self.mode == HALMode.SIM:
            self._init_sim_sensors()
        else:
            self._init_real_sensors()
        self._active = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="sensemesh-poll", daemon=True)
        self._poll_thread.start()
        self._ready = True
        self.log.info(f"SenseMesh started | polling={self._poll_ms}ms | "
                      f"mode={self.mode.value}")
        return True

    def _init_sim_sensors(self) -> None:
        """Register synthetic sensor catalog."""
        sensors = [
            ("TMP_GPU0_INLET", "GPU0_inlet",    "C"),
            ("TMP_GPU1_INLET", "GPU1_inlet",    "C"),
            ("TMP_GPU2_INLET", "GPU2_inlet",    "C"),
            ("TMP_GPU3_INLET", "GPU3_inlet",    "C"),
            ("TMP_CPU",        "CPU_package",   "C"),
            ("TMP_INLET",      "Chassis_inlet", "C"),
            ("INA_GPUA_V",     "GPU_ZONE_A_V",  "V"),
            ("INA_GPUA_I",     "GPU_ZONE_A_mA", "mA"),
            ("INA_GPUA_P",     "GPU_ZONE_A_W",  "W"),
            ("INA_GPUB_V",     "GPU_ZONE_B_V",  "V"),
            ("INA_GPUB_I",     "GPU_ZONE_B_mA", "mA"),
            ("INA_GPUB_P",     "GPU_ZONE_B_W",  "W"),
            ("INA_HOST_V",     "HOST_12V",       "V"),
            ("INA_HOST_I",     "HOST_mA",        "mA"),
            ("INA_HOST_P",     "HOST_W",         "W"),
        ]
        for sid, label, unit in sensors:
            self._readings[sid] = SensorReading(sid, label, 0.0, unit)

    def _init_real_sensors(self) -> None:
        """Enumerate real I2C devices via /sys/bus/i2c/devices/."""
        for bus_cfg in self._i2c_buses:
            bus = bus_cfg.get("bus", 0)
            for dev in bus_cfg.get("devices", []):
                addr  = dev.get("addr", "0x48")
                model = dev.get("model", "unknown")
                label = dev.get("label", f"sensor_{bus}_{addr}")
                sid   = f"{model}_{bus}_{addr.replace('0x','')}"
                unit  = "C" if "TMP" in model else "mA"
                sysfs = f"/sys/bus/i2c/devices/{bus}-{int(addr,16):04d}/"
                self._readings[sid] = SensorReading(sid, label, 0.0, unit)
                self.log.debug(f"Registered sensor: {sid} @ {sysfs}")

    def _poll_loop(self) -> None:
        """Background polling thread."""
        while self._active:
            try:
                if self.mode == HALMode.SIM:
                    self._poll_sim()
                else:
                    self._poll_real()
                self._check_thresholds()
                self._store_snapshot()
            except Exception as e:
                self.log.debug(f"Poll error: {e}")
            time.sleep(self._poll_ms / 1000.0)

    def _poll_sim(self) -> None:
        """Update synthetic sensor values with realistic noise."""
        now = datetime.now(timezone.utc).isoformat()
        t = time.monotonic()
        # Simulate thermal ramp over time
        base_gpu_temp = 48 + 15 * (1 - abs((t % 300) / 150 - 1))  # 0-300s cycle

        sim_values = {
            "TMP_GPU0_INLET": base_gpu_temp + random.gauss(0, 0.8),
            "TMP_GPU1_INLET": base_gpu_temp + random.gauss(1, 0.8),
            "TMP_GPU2_INLET": base_gpu_temp + random.gauss(-0.5, 0.8),
            "TMP_GPU3_INLET": base_gpu_temp + random.gauss(0.3, 0.8),
            "TMP_CPU":        55 + random.gauss(0, 1.2),
            "TMP_INLET":      23 + random.gauss(0, 0.5),
            "INA_GPUA_V":     12.0 + random.gauss(0, 0.02),
            "INA_GPUA_I":     58000 + random.gauss(0, 500),   # ~696W zone A
            "INA_GPUA_P":     (12.0 * 58000) / 1000,
            "INA_GPUB_V":     12.0 + random.gauss(0, 0.02),
            "INA_GPUB_I":     57500 + random.gauss(0, 500),
            "INA_GPUB_P":     (12.0 * 57500) / 1000,
            "INA_HOST_V":     12.0 + random.gauss(0, 0.01),
            "INA_HOST_I":     33000 + random.gauss(0, 300),   # ~396W host
            "INA_HOST_P":     (12.0 * 33000) / 1000,
        }
        for sid, value in sim_values.items():
            if sid in self._readings:
                self._readings[sid].value     = round(value, 2)
                self._readings[sid].timestamp = now

    def _poll_real(self) -> None:
        """Read from real I2C devices via sysfs hwmon."""
        for bus_cfg in self._i2c_buses:
            bus = bus_cfg.get("bus", 0)
            for dev in bus_cfg.get("devices", []):
                addr  = dev.get("addr", "0x48")
                model = dev.get("model", "TMP112")
                sid   = f"{model}_{bus}_{addr.replace('0x','')}"
                if sid not in self._readings:
                    continue
                try:
                    value = self._read_i2c_sysfs(bus, addr, model)
                    if value is not None:
                        self._readings[sid].value = value
                        self._readings[sid].timestamp = datetime.now(timezone.utc).isoformat()
                except Exception as e:
                    self.log.debug(f"I2C read error {sid}: {e}")

    def _read_i2c_sysfs(self, bus: int, addr: str, model: str) -> Optional[float]:
        """Read a sensor value from Linux hwmon sysfs."""
        addr_int = int(addr, 16)
        base_path = f"/sys/bus/i2c/devices/{bus}-{addr_int:04d}/hwmon"
        if not os.path.exists(base_path):
            return None
        hwmon_dirs = os.listdir(base_path)
        if not hwmon_dirs:
            return None
        hwmon_path = os.path.join(base_path, hwmon_dirs[0])

        if "TMP112" in model:
            temp_path = os.path.join(hwmon_path, "temp1_input")
            if os.path.exists(temp_path):
                raw = open(temp_path).read().strip()
                return float(raw) / 1000.0  # milli-°C → °C
        elif "INA3221" in model:
            # Channel 1 current
            curr_path = os.path.join(hwmon_path, "curr1_input")
            if os.path.exists(curr_path):
                raw = open(curr_path).read().strip()
                return float(raw)  # mA
        return None

    def _check_thresholds(self) -> None:
        """Check all readings against alert thresholds."""
        for sid, reading in self._readings.items():
            prev_level = reading.alert_level
            new_level  = "ok"

            if reading.unit == "C":
                if reading.value >= self._thresholds.get("temp_critical_c", 85):
                    new_level = "critical"
                elif reading.value >= self._thresholds.get("temp_warning_c", 75):
                    new_level = "warning"
            elif reading.unit == "W":
                if reading.value >= self._thresholds.get("power_critical_w", 2400):
                    new_level = "critical"
                elif reading.value >= self._thresholds.get("power_warning_w", 2200):
                    new_level = "warning"

            reading.alert_level = new_level
            # Publish event only on level transition
            if new_level != prev_level and new_level != "ok":
                self.events.publish_alert(
                    "sensemesh", new_level,
                    f"Sensor {reading.label}: {reading.value}{reading.unit}",
                    sensor_id=sid, value=reading.value, unit=reading.unit
                )

    def _store_snapshot(self) -> None:
        """Store a snapshot in the ring buffer (max 600 = 60s at 100ms)."""
        temps   = {r.label: r.value for r in self._readings.values() if r.unit == "C"}
        volts   = {r.label: r.value for r in self._readings.values() if r.unit == "V"}
        amps    = {r.label: r.value for r in self._readings.values() if r.unit == "mA"}
        powers  = {r.label: r.value for r in self._readings.values() if r.unit == "W"}
        alerts  = [r.label for r in self._readings.values() if r.alert_level != "ok"]
        snap = SensorSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            temperatures=temps, voltages=volts,
            currents=amps, powers=powers, alerts=alerts
        )
        self._history.append(snap)
        if len(self._history) > 600:
            self._history.pop(0)

    # ── Public API ─────────────────────────────────────────────────────────

    def get_reading(self, sensor_id: str) -> Optional[SensorReading]:
        return self._readings.get(sensor_id)

    def get_all_readings(self) -> Dict[str, dict]:
        return {sid: r.to_dict() for sid, r in self._readings.items()}

    def get_latest_snapshot(self) -> Optional[dict]:
        return self._history[-1].to_dict() if self._history else None

    def get_history(self, last_n: int = 60) -> List[dict]:
        return [s.to_dict() for s in self._history[-last_n:]]

    def get_active_alerts(self) -> List[dict]:
        return [r.to_dict() for r in self._readings.values() if r.alert_level != "ok"]

    def health(self) -> SubsystemHealth:
        if not self._ready:
            return SubsystemHealth("SenseMesh", "offline", self.mode.value, "Not initialised")
        alerts  = self.get_active_alerts()
        status  = "ok" if not alerts else "degraded"
        snap    = self.get_latest_snapshot() or {}
        temps   = snap.get("temperatures", {})
        max_t   = max(temps.values(), default=0)
        total_w = sum(snap.get("powers", {}).values())
        return SubsystemHealth(
            "SenseMesh", status, self.mode.value,
            f"{len(self._readings)} sensors | max_temp={max_t:.1f}°C | "
            f"total_power={total_w:.0f}W | alerts={len(alerts)}",
            metrics={"sensor_count": len(self._readings),
                     "max_temp_c": round(max_t, 1),
                     "total_power_w": round(total_w, 0),
                     "active_alerts": len(alerts)}
        )

    def shutdown(self) -> None:
        self._active = False
        if self._poll_thread:
            self._poll_thread.join(timeout=2)
        self.log.info("SenseMesh shutdown complete")
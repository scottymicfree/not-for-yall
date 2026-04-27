"""
Cipher Detector
Analyzes input text and returns ranked cipher matches using:
  - Index of Coincidence (IoC)
  - Frequency analysis
  - Pattern detection rules
  - Structural heuristics
"""
from __future__ import annotations
import re
import math
import string
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from .cipher_db import cipher_db, CipherEntry


@dataclass
class CipherMatch:
    cipher_id: str
    cipher_name: str
    category: str
    confidence: float          # 0.0 – 1.0
    ioc: float
    matched_rules: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "cipher_id": self.cipher_id,
            "cipher_name": self.cipher_name,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "ioc": round(self.ioc, 6),
            "matched_rules": self.matched_rules,
            "notes": self.notes,
        }


@dataclass
class DetectionResult:
    text_length: int
    ioc: float
    letter_freq: Dict[str, float]
    top_matches: List[CipherMatch]
    structural_flags: List[str]
    entropy: float

    def to_dict(self) -> dict:
        return {
            "text_length": self.text_length,
            "ioc": round(self.ioc, 6),
            "entropy": round(self.entropy, 4),
            "letter_freq": {k: round(v, 4) for k, v in self.letter_freq.items()},
            "structural_flags": self.structural_flags,
            "top_matches": [m.to_dict() for m in self.top_matches],
        }


# ── English letter frequencies (reference) ────────────────────────────────────
ENGLISH_FREQ: Dict[str, float] = {
    'e': 0.1270, 't': 0.0906, 'a': 0.0817, 'o': 0.0751, 'i': 0.0697,
    'n': 0.0675, 's': 0.0633, 'h': 0.0609, 'r': 0.0599, 'd': 0.0425,
    'l': 0.0403, 'c': 0.0278, 'u': 0.0276, 'm': 0.0241, 'w': 0.0234,
    'f': 0.0223, 'g': 0.0202, 'y': 0.0197, 'p': 0.0193, 'b': 0.0149,
    'v': 0.0098, 'k': 0.0077, 'j': 0.0015, 'x': 0.0015, 'q': 0.0010,
    'z': 0.0007,
}

ENGLISH_IOC = 0.0655   # Theoretical English IoC
RANDOM_IOC  = 0.0385   # Random text IoC


def compute_ioc(text: str) -> float:
    """Compute Index of Coincidence for alphabetic characters."""
    letters = [c.lower() for c in text if c.isalpha()]
    n = len(letters)
    if n < 2:
        return 0.0
    counts = Counter(letters)
    total = sum(f * (f - 1) for f in counts.values())
    return total / (n * (n - 1))


def compute_entropy(text: str) -> float:
    """Shannon entropy of the text bytes."""
    if not text:
        return 0.0
    counts = Counter(text)
    total = len(text)
    entropy = 0.0
    for c in counts.values():
        p = c / total
        entropy -= p * math.log2(p)
    return entropy


def letter_frequencies(text: str) -> Dict[str, float]:
    """Relative frequency of each letter in text."""
    letters = [c.lower() for c in text if c.isalpha()]
    n = len(letters)
    if n == 0:
        return {}
    counts = Counter(letters)
    return {ch: counts.get(ch, 0) / n for ch in string.ascii_lowercase}


def freq_chi_squared(observed: Dict[str, float], expected: Dict[str, float]) -> float:
    """Chi-squared distance between observed and expected frequency distributions."""
    total = 0.0
    for ch in string.ascii_lowercase:
        o = observed.get(ch, 0)
        e = expected.get(ch, 0)
        if e > 0:
            total += ((o - e) ** 2) / e
    return total


def best_caesar_chi2(text: str) -> Tuple[int, float]:
    """Find best Caesar shift by minimum chi-squared. Returns (shift, chi2)."""
    letters = [c.lower() for c in text if c.isalpha()]
    n = len(letters)
    if n == 0:
        return 0, 9999.0
    best_shift, best_chi2 = 0, float('inf')
    for shift in range(26):
        shifted = [(ord(c) - ord('a') - shift) % 26 for c in letters]
        counts = Counter(shifted)
        obs = {chr(ord('a') + i): counts.get(i, 0) / n for i in range(26)}
        chi2 = freq_chi_squared(obs, ENGLISH_FREQ)
        if chi2 < best_chi2:
            best_chi2 = chi2
            best_shift = shift
    return best_shift, best_chi2


def detect_structural_flags(text: str) -> List[str]:
    """Detect structural patterns that indicate specific cipher families."""
    flags = []
    stripped = text.strip()

    # Base64
    if re.match(r'^[A-Za-z0-9+/]+={0,2}$', stripped) and len(stripped) % 4 == 0:
        flags.append("base64_pattern")

    # Hex
    if re.match(r'^[0-9a-fA-F]+$', stripped) and len(stripped) % 2 == 0:
        flags.append("hex_encoding")

    # Base32
    if re.match(r'^[A-Z2-7]+=*$', stripped) and len(stripped) % 8 == 0:
        flags.append("base32_pattern")

    # Only A,D,F,G,V,X characters → ADFGVX
    alpha_chars = set(c.upper() for c in stripped if c.isalpha())
    if alpha_chars and alpha_chars <= {'A', 'D', 'F', 'G', 'V', 'X'}:
        flags.append("adfgvx_chars")
    elif alpha_chars and alpha_chars <= {'A', 'D', 'F', 'G', 'X'}:
        flags.append("adfgx_chars")

    # Numeric pairs 11-55 → Polybius family
    nums = re.findall(r'\b[1-5][1-5]\b', stripped)
    if len(nums) > 5 and len(nums) * 2 >= len(stripped.split()) * 0.8:
        flags.append("polybius_pairs")

    # Dot-dash → Morse
    if re.match(r'^[\.\-\s/]+$', stripped):
        flags.append("morse_pattern")

    # Binary string
    if re.match(r'^[01\s]+$', stripped) and len(stripped.replace(' ', '')) > 10:
        flags.append("binary_string")

    # bcrypt hash
    if re.match(r'^\$2[aby]\$\d+\$', stripped):
        flags.append("bcrypt_hash")

    # MD5 (32 hex)
    if re.match(r'^[0-9a-fA-F]{32}$', stripped):
        flags.append("md5_hash")

    # SHA1 (40 hex)
    if re.match(r'^[0-9a-fA-F]{40}$', stripped):
        flags.append("sha1_hash")

    # SHA256 (64 hex)
    if re.match(r'^[0-9a-fA-F]{64}$', stripped):
        flags.append("sha256_hash")

    # Zero-width chars
    zw_chars = {'\u200b', '\u200c', '\u200d', '\ufeff', '\u2060'}
    if any(c in stripped for c in zw_chars):
        flags.append("zero_width_chars")

    # Only A-B characters (Bacon's cipher)
    if re.match(r'^[ABab\s]+$', stripped) and len(stripped.replace(' ', '')) % 5 == 0:
        flags.append("bacon_binary")

    # Uniformly uppercase with high IoC → monoalphabetic
    alpha_only = ''.join(c for c in stripped if c.isalpha())
    if alpha_only and alpha_only == alpha_only.upper() and len(alpha_only) > 20:
        flags.append("all_uppercase")

    # No letter self-encryption check (Enigma property)
    # Not directly detectable from ciphertext alone

    return flags


class CipherDetector:
    """Detect likely cipher(s) for a given ciphertext."""

    def detect(self, text: str, top_n: int = 5) -> DetectionResult:
        """Analyze text and return top N cipher matches with confidence scores."""
        ioc = compute_ioc(text)
        entropy = compute_entropy(text)
        freq = letter_frequencies(text)
        flags = detect_structural_flags(text)
        n = len(text)

        matches: List[CipherMatch] = []

        # ── Structural flag shortcuts ──────────────────────────────────────
        if "base64_pattern" in flags:
            matches.append(CipherMatch("C048", "Base64", "Encoding",
                confidence=0.92, ioc=ioc,
                matched_rules=["base64_pattern: A-Za-z0-9+/= only, len%4==0"],
                notes="Likely Base64 encoding"))

        if "base32_pattern" in flags:
            matches.append(CipherMatch("C049", "Base32", "Encoding",
                confidence=0.90, ioc=ioc,
                matched_rules=["base32_pattern: A-Z2-7 only, len%8==0"]))

        if "hex_encoding" in flags:
            matches.append(CipherMatch("C051", "Hex Encoding", "Encoding",
                confidence=0.90, ioc=ioc,
                matched_rules=["hex_encoding: 0-9A-F only, even length"]))

        if "morse_pattern" in flags:
            matches.append(CipherMatch("C020", "Morse Code", "Encoding",
                confidence=0.95, ioc=ioc,
                matched_rules=["morse_pattern: . - / chars only"]))

        if "bcrypt_hash" in flags:
            matches.append(CipherMatch("C059", "bcrypt", "Modern",
                confidence=0.99, ioc=ioc,
                matched_rules=["bcrypt_hash: $2[aby]$ prefix"]))

        if "md5_hash" in flags:
            matches.append(CipherMatch("C044", "MD5", "Encoding",
                confidence=0.90, ioc=ioc,
                matched_rules=["md5_hash: 32 hex chars"]))

        if "sha1_hash" in flags:
            matches.append(CipherMatch("C045", "SHA-1", "Encoding",
                confidence=0.90, ioc=ioc,
                matched_rules=["sha1_hash: 40 hex chars"]))

        if "sha256_hash" in flags:
            matches.append(CipherMatch("C046", "SHA-256", "Encoding",
                confidence=0.90, ioc=ioc,
                matched_rules=["sha256_hash: 64 hex chars"]))

        if "zero_width_chars" in flags:
            matches.append(CipherMatch("C063", "Zero-Width Character Steganography",
                "Steganographic", confidence=0.88, ioc=ioc,
                matched_rules=["zero_width_chars: U+200B/C/D/FEFF found"]))

        if "bacon_binary" in flags:
            matches.append(CipherMatch("C067", "Bacon's Cipher", "Steganographic",
                confidence=0.82, ioc=ioc,
                matched_rules=["bacon_binary: A/B chars only, len%5==0"]))

        if "polybius_pairs" in flags:
            for cid, name in [("C014", "Polybius Square"), ("C069", "Tap Code"),
                               ("C070", "Nihilist Cipher")]:
                matches.append(CipherMatch(cid, name, "Classical",
                    confidence=0.75, ioc=ioc,
                    matched_rules=["polybius_pairs: numeric pairs 11-55"]))

        if "adfgvx_chars" in flags:
            matches.append(CipherMatch("C015", "ADFGVX Cipher", "Classical",
                confidence=0.88, ioc=ioc,
                matched_rules=["adfgvx_chars: only A,D,F,G,V,X letters"]))

        if "adfgx_chars" in flags:
            matches.append(CipherMatch("C016", "ADFGX Cipher", "Classical",
                confidence=0.85, ioc=ioc,
                matched_rules=["adfgx_chars: only A,D,F,G,X letters"]))

        # ── IoC-based analysis ─────────────────────────────────────────────
        letters = ''.join(c for c in text if c.isalpha())
        has_alpha = len(letters) > 10

        if has_alpha:
            # Near English IoC → monoalphabetic substitution family
            if 0.060 <= ioc <= 0.070:
                _, chi2 = best_caesar_chi2(text)
                if chi2 < 200:   # Very good Caesar fit
                    matches.append(CipherMatch("C001", "Caesar Cipher", "Classical",
                        confidence=min(0.90, 0.90 - chi2/5000),
                        ioc=ioc,
                        matched_rules=[
                            f"IoC={ioc:.4f} near English",
                            f"Chi-squared={chi2:.1f} (low = good fit)",
                        ]))
                    matches.append(CipherMatch("C003", "ROT13", "Classical",
                        confidence=0.70, ioc=ioc,
                        matched_rules=["IoC near English", "Caesar-13 candidate"]))

                matches.append(CipherMatch("C004", "Simple Substitution Cipher", "Classical",
                    confidence=0.75, ioc=ioc,
                    matched_rules=[f"IoC={ioc:.4f} near English (monoalphabetic)"]))
                matches.append(CipherMatch("C002", "Atbash Cipher", "Classical",
                    confidence=0.65, ioc=ioc,
                    matched_rules=["IoC near English — Atbash candidate"]))
                matches.append(CipherMatch("C018", "Keyword Cipher", "Classical",
                    confidence=0.65, ioc=ioc,
                    matched_rules=["IoC near English — keyword substitution candidate"]))

                if "all_uppercase" in flags:
                    # Transposition ciphers also have English IoC
                    matches.append(CipherMatch("C022", "Columnar Transposition", "Transposition",
                        confidence=0.60, ioc=ioc,
                        matched_rules=["IoC=English (transposition preserves freq)", "all_uppercase"]))
                    matches.append(CipherMatch("C021", "Rail Fence Cipher", "Transposition",
                        confidence=0.55, ioc=ioc,
                        matched_rules=["IoC=English, all uppercase"]))

            # Depressed IoC → polyalphabetic
            elif 0.038 <= ioc < 0.060:
                vigenere_conf = 1.0 - (ioc - RANDOM_IOC) / (ENGLISH_IOC - RANDOM_IOC)
                vigenere_conf = max(0.1, min(0.92, vigenere_conf))
                matches.append(CipherMatch("C006", "Vigenère Cipher", "Polyalphabetic",
                    confidence=vigenere_conf, ioc=ioc,
                    matched_rules=[
                        f"IoC={ioc:.4f} between random({RANDOM_IOC}) and English({ENGLISH_IOC})",
                        "Kasiski examination recommended",
                    ]))
                matches.append(CipherMatch("C007", "Beaufort Cipher", "Polyalphabetic",
                    confidence=vigenere_conf * 0.85, ioc=ioc,
                    matched_rules=["Similar IoC to Vigenère"]))
                matches.append(CipherMatch("C009", "Autokey Cipher", "Polyalphabetic",
                    confidence=vigenere_conf * 0.80, ioc=ioc,
                    matched_rules=["Polyalphabetic family"]))
                matches.append(CipherMatch("C052", "XOR Cipher", "Modern",
                    confidence=0.55, ioc=ioc,
                    matched_rules=["Multi-byte XOR has Vigenère-like IoC"]))

            # Near random IoC → modern cipher or OTP
            elif ioc < 0.042:
                high_entropy = entropy > 7.0
                matches.append(CipherMatch("C031", "One-Time Pad (OTP)", "Modern",
                    confidence=0.50 if not high_entropy else 0.35, ioc=ioc,
                    matched_rules=[f"IoC={ioc:.4f} near random", "Near-random distribution"]))
                matches.append(CipherMatch("C037", "AES-128", "Modern",
                    confidence=0.45, ioc=ioc,
                    matched_rules=["IoC near random — block cipher output"]))
                matches.append(CipherMatch("C038", "AES-256", "Modern",
                    confidence=0.40, ioc=ioc,
                    matched_rules=["IoC near random"]))
                matches.append(CipherMatch("C027", "Enigma Machine", "Mechanical",
                    confidence=0.35, ioc=ioc,
                    matched_rules=["IoC near random + alphabetic output"]))

        # ── Entropy-based refinement ───────────────────────────────────────
        if entropy > 7.5:
            # Very high entropy → binary/compressed/encrypted
            for m in matches:
                if m.category in ("Modern", "Mechanical"):
                    m.confidence = min(0.95, m.confidence * 1.1)
            if not any(m.cipher_id in ("C037", "C038") for m in matches):
                matches.append(CipherMatch("C038", "AES-256", "Modern",
                    confidence=0.40, ioc=ioc,
                    matched_rules=["High entropy (>7.5 bits)"]))

        # ── Deduplicate by cipher_id, keep highest confidence ──────────────
        seen: dict[str, CipherMatch] = {}
        for m in matches:
            if m.cipher_id not in seen or m.confidence > seen[m.cipher_id].confidence:
                seen[m.cipher_id] = m
        matches = sorted(seen.values(), key=lambda x: x.confidence, reverse=True)

        return DetectionResult(
            text_length=n,
            ioc=ioc,
            letter_freq=freq,
            top_matches=matches[:top_n],
            structural_flags=flags,
            entropy=entropy,
        )


# Singleton
detector = CipherDetector()
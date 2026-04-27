"""
Cipher Intelligence Database
78 cipher entries with IoC ranges, detection rules, frequency analysis flags.
Ported from the CIPHERS JavaScript dataset provided in the LucyMesh materials.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

@dataclass
class CipherEntry:
    id: str
    name: str
    category: str          # Classical | Polyalphabetic | Transposition | Modern | Steganographic | Encoding
    era: str               # Ancient | Medieval | Renaissance | Modern | Contemporary
    ioc_min: float         # Index of Coincidence range
    ioc_max: float
    key_space: str         # small | medium | large | infinite
    frequency_flag: bool   # True if frequency analysis is applicable
    detection_rules: List[str]
    description: str
    tags: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── 78 Cipher Entries ──────────────────────────────────────────────────────────

CIPHERS: List[CipherEntry] = [
    # ── Classical Substitution ──────────────────────────────────────────────
    CipherEntry("C001", "Caesar Cipher", "Classical", "Ancient",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=True,
        detection_rules=[
            "IoC near 0.065-0.068 (English)",
            "Uniform letter shift detectable",
            "Frequency distribution matches shifted English",
            "26 possible keys — exhaustive search trivial",
        ],
        description="Monoalphabetic substitution with fixed shift. ROT13 is Caesar-13.",
        tags=["monoalphabetic", "substitution", "shift", "rot13"]),

    CipherEntry("C002", "Atbash Cipher", "Classical", "Ancient",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=True,
        detection_rules=[
            "IoC near English (~0.065)",
            "A↔Z, B↔Y mirror substitution",
            "Frequency histogram mirrors English",
            "Self-inverse — decryption == encryption",
        ],
        description="Hebrew mirror cipher. A=Z, B=Y, ... Z=A.",
        tags=["monoalphabetic", "substitution", "mirror", "hebrew"]),

    CipherEntry("C003", "ROT13", "Classical", "Modern",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=True,
        detection_rules=[
            "IoC ~0.065",
            "Caesar-13 special case",
            "Common in Usenet/forums for spoiler hiding",
            "All alpha chars shifted by 13",
        ],
        description="Caesar cipher with shift 13. Self-inverse.",
        tags=["monoalphabetic", "caesar", "rot13", "internet"]),

    CipherEntry("C004", "Simple Substitution Cipher", "Classical", "Ancient",
        ioc_min=0.065, ioc_max=0.068,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "IoC near English plaintext (~0.065)",
            "25! key space but frequency analysis breaks it",
            "Most frequent ciphertext letter → E",
            "Digraph/trigraph patterns preserved",
        ],
        description="Random permutation of the alphabet as substitution key.",
        tags=["monoalphabetic", "substitution", "frequency"]),

    CipherEntry("C005", "Affine Cipher", "Classical", "Ancient",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=True,
        detection_rules=[
            "IoC ~0.065",
            "E(x) = (ax + b) mod 26",
            "Only 12 valid 'a' values (coprime with 26)",
            "312 total possible keys",
        ],
        description="Generalization of Caesar: E(x) = (ax+b) mod 26.",
        tags=["monoalphabetic", "affine", "mathematical"]),

    CipherEntry("C006", "Vigenère Cipher", "Polyalphabetic", "Renaissance",
        ioc_min=0.040, ioc_max=0.060,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "IoC 0.040-0.060 (between random and English)",
            "Kasiski examination reveals key length",
            "IoC of substrings at key-length intervals approaches 0.065",
            "Friedman test estimates key length",
        ],
        description="Polyalphabetic cipher using repeating keyword.",
        tags=["polyalphabetic", "keyword", "kasiski", "friedman"]),

    CipherEntry("C007", "Beaufort Cipher", "Polyalphabetic", "Renaissance",
        ioc_min=0.040, ioc_max=0.060,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "Similar IoC profile to Vigenère",
            "E(x) = (k - p) mod 26 (reciprocal variant)",
            "Self-inverse: same operation encrypts and decrypts",
            "Kasiski/Friedman applicable",
        ],
        description="Variant of Vigenère: E = key − plaintext mod 26.",
        tags=["polyalphabetic", "beaufort", "reciprocal"]),

    CipherEntry("C008", "Gronsfeld Cipher", "Polyalphabetic", "Renaissance",
        ioc_min=0.042, ioc_max=0.058,
        key_space="medium",
        frequency_flag=True,
        detection_rules=[
            "Key digits 0-9 only (weaker than Vigenère)",
            "IoC slightly higher than Vigenère due to limited key space",
            "Kasiski examination applicable",
        ],
        description="Vigenère variant using numeric key (digits 0-9).",
        tags=["polyalphabetic", "numeric-key", "vigenere-variant"]),

    CipherEntry("C009", "Autokey Cipher", "Polyalphabetic", "Renaissance",
        ioc_min=0.060, ioc_max=0.065,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "IoC close to English (key extends with plaintext)",
            "Resists Kasiski — no repeating key cycle",
            "Statistical attacks on key primer still possible",
        ],
        description="Vigenère variant where key is extended by plaintext itself.",
        tags=["polyalphabetic", "autokey", "self-keying"]),

    CipherEntry("C010", "Running Key Cipher", "Polyalphabetic", "Modern",
        ioc_min=0.064, ioc_max=0.067,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "IoC near English (key is natural language text)",
            "Statistically indistinguishable from OTP if key is random",
            "Vulnerable if key source (book page) can be guessed",
        ],
        description="Key is a long natural-language text (e.g., a book passage).",
        tags=["polyalphabetic", "running-key", "book-cipher"]),

    CipherEntry("C011", "Playfair Cipher", "Classical", "Modern",
        ioc_min=0.045, ioc_max=0.055,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "Digraph substitution — odd total length → padding char",
            "No letter pair in ciphertext (same-letter digraphs padded)",
            "25-letter alphabet (I=J typically merged)",
            "IoC lower than monoalphabetic",
        ],
        description="Digraph substitution cipher using 5×5 key square.",
        tags=["digraph", "substitution", "5x5", "square"]),

    CipherEntry("C012", "Four-Square Cipher", "Classical", "Modern",
        ioc_min=0.044, ioc_max=0.054,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "Digraph substitution using 4 squares",
            "Two key squares + two standard alphabet squares",
            "Similar analysis to Playfair",
        ],
        description="Polybius-family digraph cipher with four 5×5 squares.",
        tags=["digraph", "four-square", "polybius"]),

    CipherEntry("C013", "Two-Square Cipher", "Classical", "Modern",
        ioc_min=0.044, ioc_max=0.054,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "Digraph substitution using 2 squares",
            "Horizontal or vertical variant",
        ],
        description="Simplified four-square using only two 5×5 key matrices.",
        tags=["digraph", "two-square", "polybius"]),

    CipherEntry("C014", "Polybius Square", "Classical", "Ancient",
        ioc_min=0.040, ioc_max=0.060,
        key_space="medium",
        frequency_flag=True,
        detection_rules=[
            "Numeric pairs 11-55 (or 1-5 pairs)",
            "25 distinct symbols/pairs",
            "Frequent pairs correlate with E,T,A",
        ],
        description="Converts letters to numeric coordinates on a 5×5 grid.",
        tags=["polybius", "numeric", "coordinate"]),

    CipherEntry("C015", "ADFGVX Cipher", "Classical", "Modern",
        ioc_min=0.038, ioc_max=0.050,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "Only letters A,D,F,G,V,X appear",
            "Even-length ciphertext (fractionation)",
            "WWI German field cipher",
            "Columnar transposition applied after substitution",
        ],
        description="WWI German cipher: fractionating substitution + columnar transposition.",
        tags=["fractionating", "transposition", "wwi", "german"]),

    CipherEntry("C016", "ADFGX Cipher", "Classical", "Modern",
        ioc_min=0.038, ioc_max=0.050,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "Only letters A,D,F,G,X appear",
            "Predecessor to ADFGVX",
            "25-letter alphabet",
        ],
        description="Predecessor to ADFGVX (5 symbols, 5×5 grid).",
        tags=["fractionating", "transposition", "wwi"]),

    CipherEntry("C017", "Hill Cipher", "Classical", "Modern",
        ioc_min=0.035, ioc_max=0.055,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "Matrix multiplication mod 26",
            "Block size n determines key matrix n×n",
            "Known-plaintext attack breaks it easily",
            "IoC depends on block size — larger blocks lower IoC",
        ],
        description="Linear algebra cipher: C = K·P mod 26 (matrix multiplication).",
        tags=["matrix", "linear-algebra", "block"]),

    CipherEntry("C018", "Keyword Cipher", "Classical", "Ancient",
        ioc_min=0.065, ioc_max=0.068,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "IoC near English (monoalphabetic)",
            "Alphabet starts with non-repeating keyword letters",
            "Frequency analysis straightforward",
        ],
        description="Monoalphabetic substitution with keyword-ordered alphabet.",
        tags=["monoalphabetic", "keyword", "substitution"]),

    CipherEntry("C019", "Pigpen Cipher", "Classical", "Ancient",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=True,
        detection_rules=[
            "Geometric symbol substitution",
            "Grid/cross/X patterns",
            "Masonic cipher variant",
        ],
        description="Geometric substitution cipher used by Freemasons.",
        tags=["symbolic", "geometric", "masonic", "visual"]),

    CipherEntry("C020", "Morse Code", "Encoding", "Modern",
        ioc_min=0.050, ioc_max=0.070,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "Only dots, dashes, spaces",
            "Variable-length codes per letter",
            "E='.', T='-' most frequent",
        ],
        description="Dot-dash encoding for telegraph communication.",
        tags=["encoding", "dots-dashes", "telegraph"]),

    # ── Transposition Ciphers ───────────────────────────────────────────────
    CipherEntry("C021", "Rail Fence Cipher", "Transposition", "Ancient",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=True,
        detection_rules=[
            "IoC identical to plaintext (only transposition)",
            "Letter frequency preserved",
            "Rail count determines pattern",
        ],
        description="Zigzag transposition across N rails.",
        tags=["transposition", "zigzag", "rail"]),

    CipherEntry("C022", "Columnar Transposition", "Transposition", "Modern",
        ioc_min=0.065, ioc_max=0.068,
        key_space="medium",
        frequency_flag=True,
        detection_rules=[
            "IoC identical to plaintext",
            "Anagramming reveals columns",
            "Column lengths differ by at most 1",
        ],
        description="Rearrange plaintext by writing in rows and reading by columns.",
        tags=["transposition", "columnar", "keyword"]),

    CipherEntry("C023", "Double Transposition", "Transposition", "Modern",
        ioc_min=0.065, ioc_max=0.068,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "IoC identical to plaintext (pure transposition)",
            "Columnar transposition applied twice",
            "Much stronger than single transposition",
        ],
        description="Columnar transposition applied twice with same or different keys.",
        tags=["transposition", "double", "columnar"]),

    CipherEntry("C024", "Scytale", "Transposition", "Ancient",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=True,
        detection_rules=[
            "IoC identical to plaintext",
            "Width (diameter) of rod is key",
            "Sparta military cipher",
        ],
        description="Ancient Spartan transposition cipher using a rod (scytale).",
        tags=["transposition", "spartan", "rod", "ancient"]),

    CipherEntry("C025", "Route Cipher", "Transposition", "Modern",
        ioc_min=0.065, ioc_max=0.068,
        key_space="medium",
        frequency_flag=True,
        detection_rules=[
            "IoC identical to plaintext",
            "Reading route (spiral, diagonal, etc.) determines cipher",
        ],
        description="Text written in grid, read out in a specified route/path.",
        tags=["transposition", "route", "grid"]),

    CipherEntry("C026", "Myszkowski Transposition", "Transposition", "Modern",
        ioc_min=0.065, ioc_max=0.068,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "IoC identical to plaintext",
            "Repeated keyword letters create groups",
            "Variant of columnar transposition",
        ],
        description="Columnar transposition variant with repeated-letter key handling.",
        tags=["transposition", "myszkowski", "columnar"]),

    # ── Mechanical / Rotor Ciphers ──────────────────────────────────────────
    CipherEntry("C027", "Enigma Machine", "Mechanical", "Modern",
        ioc_min=0.038, ioc_max=0.048,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "No letter encrypts to itself (reflector property)",
            "IoC near random (0.038-0.048)",
            "Known-plaintext cribs (e.g., 'KEINE BESONDEREN EREIGNISSE')",
            "Bombe machine exploits cribs + no-self-encryption",
        ],
        description="German WWII electromechanical rotor cipher machine.",
        tags=["rotor", "mechanical", "enigma", "wwii", "german"]),

    CipherEntry("C028", "Lorenz SZ40/42", "Mechanical", "Modern",
        ioc_min=0.033, ioc_max=0.043,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Teleprinter (Baudot code) basis",
            "Statistical depth attacks (Tutte's method)",
            "Colossus computer used to break it",
        ],
        description="German WWII Lorenz cipher machine (Tunny). Broken by Colossus.",
        tags=["rotor", "mechanical", "lorenz", "wwii", "bletchley"]),

    CipherEntry("C029", "Typex", "Mechanical", "Modern",
        ioc_min=0.038, ioc_max=0.048,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "British Enigma variant",
            "5 rotors vs Enigma's 3",
            "Similar statistical profile to Enigma",
        ],
        description="British WWII cipher machine, Enigma-compatible variant.",
        tags=["rotor", "mechanical", "british", "wwii"]),

    CipherEntry("C030", "SIGABA", "Mechanical", "Modern",
        ioc_min=0.033, ioc_max=0.043,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "15 rotors (5 cipher, 5 control, 5 index)",
            "Never broken during WWII",
            "US military cipher machine",
        ],
        description="US WWII cipher machine (ECM Mark II). Never cryptanalyzed.",
        tags=["rotor", "mechanical", "us-military", "wwii", "unbroken"]),

    # ── One-Time Pad & Stream ───────────────────────────────────────────────
    CipherEntry("C031", "One-Time Pad (OTP)", "Modern", "Modern",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "IoC indistinguishable from random if key is truly random",
            "Provably unbreakable (Shannon's theorem)",
            "Key must be same length as message",
            "Any key plausible — deniability possible",
        ],
        description="Provably perfect secrecy. XOR with random key same length as message.",
        tags=["otp", "perfect-secrecy", "xor", "shannon"]),

    CipherEntry("C032", "RC4 Stream Cipher", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.040,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "First two bytes biased (Fluhrer-Mantin-Shamir)",
            "Used in WEP (broken), TLS (deprecated)",
            "Statistical biases in keystream",
        ],
        description="Software stream cipher. Deprecated due to biases.",
        tags=["stream", "rc4", "deprecated", "wep"]),

    CipherEntry("C033", "ChaCha20", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "256-bit key, 64-bit nonce",
            "No known practical attacks",
            "Used in TLS 1.3, WireGuard",
        ],
        description="Modern stream cipher by Bernstein. Replaces RC4.",
        tags=["stream", "chacha20", "modern", "secure"]),

    CipherEntry("C034", "Salsa20", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Predecessor to ChaCha20",
            "256-bit key, 64-bit nonce",
        ],
        description="Stream cipher predecessor to ChaCha20.",
        tags=["stream", "salsa20", "bernstein"]),

    # ── Block Ciphers ───────────────────────────────────────────────────────
    CipherEntry("C035", "DES", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="medium",
        frequency_flag=False,
        detection_rules=[
            "56-bit key (insecure — brute-forceable)",
            "64-bit block size",
            "ECB mode: identical blocks → identical ciphertext",
        ],
        description="56-bit key block cipher. Broken by exhaustive search (EFF DES Cracker).",
        tags=["block", "des", "deprecated", "56-bit"]),

    CipherEntry("C036", "3DES (Triple DES)", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "112-bit effective security (3 DES keys)",
            "64-bit block — Sweet32 birthday attack",
            "Slower than AES",
        ],
        description="DES applied three times. Legacy, deprecated.",
        tags=["block", "3des", "legacy", "deprecated"]),

    CipherEntry("C037", "AES-128", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "128-bit key, 128-bit block",
            "ECB mode leaks patterns",
            "No practical attacks on AES itself",
        ],
        description="Advanced Encryption Standard. NIST standard. 128-bit key.",
        tags=["block", "aes", "nist", "secure", "128"]),

    CipherEntry("C038", "AES-256", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "256-bit key, 128-bit block",
            "Slightly weaker key schedule than AES-128 (related-key attacks)",
            "Government/military standard",
        ],
        description="AES with 256-bit key. NSA Suite B approved.",
        tags=["block", "aes", "256", "nsa", "secure"]),

    CipherEntry("C039", "Blowfish", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "64-bit block (Sweet32 vulnerable for large data)",
            "Variable key: 32-448 bits",
            "Slow key setup (bcrypt uses this)",
        ],
        description="Bruce Schneier's block cipher. Used in bcrypt.",
        tags=["block", "blowfish", "schneier", "bcrypt"]),

    CipherEntry("C040", "Twofish", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "128-bit block, 128/192/256-bit key",
            "AES finalist",
            "No practical attacks known",
        ],
        description="AES finalist by Bruce Schneier et al. 128-bit block.",
        tags=["block", "twofish", "aes-finalist", "schneier"]),

    # ── Public Key / Asymmetric ─────────────────────────────────────────────
    CipherEntry("C041", "RSA", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Public/private key pair",
            "Security based on integer factorization",
            "Small keys (512/1024-bit) broken",
            "Textbook RSA without padding is deterministic",
        ],
        description="RSA public-key cryptosystem. Factorization-hard.",
        tags=["asymmetric", "rsa", "public-key", "factorization"]),

    CipherEntry("C042", "Elliptic Curve (ECC)", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Smaller key sizes vs RSA for equivalent security",
            "Discrete logarithm on elliptic curve",
            "ECDH, ECDSA variants",
        ],
        description="ECC: shorter keys, same security as RSA.",
        tags=["asymmetric", "ecc", "elliptic-curve", "ecdh"]),

    CipherEntry("C043", "ElGamal", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Probabilistic encryption — same plaintext → different ciphertext",
            "Based on discrete logarithm",
            "Ciphertext twice length of plaintext",
        ],
        description="Public-key encryption based on DLP. Probabilistic.",
        tags=["asymmetric", "elgamal", "dlp", "probabilistic"]),

    # ── Hash-based / MAC ────────────────────────────────────────────────────
    CipherEntry("C044", "MD5", "Encoding", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "128-bit output (32 hex chars)",
            "Collision attacks known (2^18 complexity)",
            "Length extension attacks",
            "Still used for checksums (not security)",
        ],
        description="128-bit cryptographic hash. Broken for collision resistance.",
        tags=["hash", "md5", "broken", "checksum"]),

    CipherEntry("C045", "SHA-1", "Encoding", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "160-bit output (40 hex chars)",
            "SHAttered attack (2017) — collision found",
            "Deprecated in TLS/certificates",
        ],
        description="160-bit SHA hash. Collision demonstrated by Google (SHAttered).",
        tags=["hash", "sha1", "deprecated", "collision"]),

    CipherEntry("C046", "SHA-256", "Encoding", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "256-bit output (64 hex chars)",
            "No practical attacks known",
            "Bitcoin uses SHA-256d (double SHA-256)",
        ],
        description="SHA-2 family. 256-bit output. Widely used standard.",
        tags=["hash", "sha256", "sha2", "secure", "bitcoin"]),

    CipherEntry("C047", "SHA-3 / Keccak", "Encoding", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Sponge construction (unlike SHA-2 Merkle-Damgård)",
            "Immune to length extension attacks",
            "NIST standard since 2015",
        ],
        description="SHA-3 based on Keccak sponge construction.",
        tags=["hash", "sha3", "keccak", "sponge"]),

    # ── Steganographic & Encoding ───────────────────────────────────────────
    CipherEntry("C048", "Base64", "Encoding", "Contemporary",
        ioc_min=0.042, ioc_max=0.052,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "Only A-Z, a-z, 0-9, +, / characters",
            "Padding with = at end",
            "Length divisible by 4",
            "Not encryption — just encoding",
        ],
        description="Binary-to-text encoding using 64-character alphabet.",
        tags=["encoding", "base64", "binary-to-text"]),

    CipherEntry("C049", "Base32", "Encoding", "Contemporary",
        ioc_min=0.044, ioc_max=0.055,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "Only A-Z, 2-7 characters",
            "Padding with = at end",
            "Length divisible by 8",
        ],
        description="Binary-to-text encoding using 32-character alphabet.",
        tags=["encoding", "base32"]),

    CipherEntry("C050", "Base58", "Encoding", "Contemporary",
        ioc_min=0.044, ioc_max=0.054,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "No 0, O, I, l (ambiguous characters removed)",
            "Bitcoin addresses use Base58Check",
        ],
        description="Bitcoin-popularized encoding without visually confusing chars.",
        tags=["encoding", "base58", "bitcoin"]),

    CipherEntry("C051", "Hex Encoding", "Encoding", "Contemporary",
        ioc_min=0.062, ioc_max=0.065,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "Only 0-9, A-F (or a-f)",
            "Length always even",
            "Each byte = 2 hex digits",
        ],
        description="Hexadecimal representation of binary data.",
        tags=["encoding", "hex", "binary"]),

    CipherEntry("C052", "XOR Cipher", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.068,
        key_space="medium",
        frequency_flag=True,
        detection_rules=[
            "Single-byte XOR: IoC ~0.065, frequency shift detectable",
            "Multi-byte XOR: Vigenère-like analysis applies",
            "Key repetition detectable via coincidence index",
            "Hamming distance method finds key length",
        ],
        description="XOR each byte with key. Trivial for single-byte key.",
        tags=["xor", "bitwise", "stream", "bitflip"]),

    # ── Nomenclators & Historical ───────────────────────────────────────────
    CipherEntry("C053", "Nomenclator", "Classical", "Medieval",
        ioc_min=0.040, ioc_max=0.060,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "Mixed substitution + codeword system",
            "Common words/names replaced by code symbols",
            "Frequency analysis on substitution portion",
        ],
        description="Hybrid cipher: substitution alphabet + codewords for common terms.",
        tags=["nomenclator", "historical", "substitution", "codebook"]),

    CipherEntry("C054", "Great Cipher (Le Chiffre Indéchiffrable)", "Classical", "Medieval",
        ioc_min=0.030, ioc_max=0.040,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "Numbers representing syllables (not letters)",
            "~587 different symbols",
            "Used by Louis XIV",
            "Unbroken for 200 years",
        ],
        description="French royal cipher encoding syllables. Unbroken until 1890.",
        tags=["syllabic", "historical", "french", "royal"]),

    CipherEntry("C055", "Chappe Telegraph Code", "Encoding", "Modern",
        ioc_min=0.038, ioc_max=0.045,
        key_space="medium",
        frequency_flag=False,
        detection_rules=[
            "Numeric codebook",
            "Optical telegraph semaphore-based",
        ],
        description="French optical telegraph encoding system (1790s).",
        tags=["telegraph", "optical", "codebook", "french"]),

    # ── Modern / Crypto ─────────────────────────────────────────────────────
    CipherEntry("C056", "Diffie-Hellman Key Exchange", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Key exchange protocol (not encryption itself)",
            "Security: discrete logarithm problem",
            "DH params (g, p) visible; shared secret is not",
        ],
        description="Key exchange over insecure channel. Not an encryption cipher.",
        tags=["key-exchange", "dh", "dlp", "protocol"]),

    CipherEntry("C057", "HMAC", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "MAC = H(key XOR opad || H(key XOR ipad || message))",
            "Fixed-length output determined by hash function",
            "HMAC-SHA256 = 64 hex chars",
        ],
        description="Hash-based Message Authentication Code.",
        tags=["mac", "hmac", "authentication", "integrity"]),

    CipherEntry("C058", "PBKDF2", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "Key derivation function",
            "Salt + iteration count visible",
            "Output is a derived key, not ciphertext",
        ],
        description="Password-Based Key Derivation Function 2.",
        tags=["kdf", "pbkdf2", "password", "salt"]),

    CipherEntry("C059", "bcrypt", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "Output starts with $2a$, $2b$, $2y$",
            "60-character output",
            "Cost factor (rounds) embedded",
            "Blowfish-based key derivation",
        ],
        description="Password hashing function based on Blowfish.",
        tags=["kdf", "bcrypt", "password", "blowfish"]),

    CipherEntry("C060", "scrypt", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "Memory-hard KDF",
            "N, r, p parameters control cost",
        ],
        description="Memory-hard password KDF. Used in Litecoin.",
        tags=["kdf", "scrypt", "memory-hard", "litecoin"]),

    # ── Steganography ───────────────────────────────────────────────────────
    CipherEntry("C061", "LSB Steganography", "Steganographic", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="medium",
        frequency_flag=False,
        detection_rules=[
            "Least significant bits of image/audio carry hidden data",
            "Statistical analysis of LSB distribution",
            "Chi-square attack detects uniform LSB distribution",
            "File size often larger than content warrants",
        ],
        description="Hide data in least-significant bits of image/audio pixels.",
        tags=["steganography", "lsb", "image", "hidden"]),

    CipherEntry("C062", "Whitespace Steganography", "Steganographic", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "Trailing spaces/tabs encode bits",
            "Invisible in most editors",
            "STEGSNOW tool commonly used",
        ],
        description="Encode data in trailing whitespace characters.",
        tags=["steganography", "whitespace", "text"]),

    CipherEntry("C063", "Zero-Width Character Steganography", "Steganographic", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "U+200B, U+200C, U+200D, U+FEFF characters",
            "Invisible in rendered text",
            "Used to fingerprint document leaks",
        ],
        description="Hide data using zero-width Unicode characters.",
        tags=["steganography", "zero-width", "unicode", "fingerprint"]),

    # ── Codes & Protocols ───────────────────────────────────────────────────
    CipherEntry("C064", "NATO Phonetic Alphabet", "Encoding", "Modern",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "Alpha, Bravo, Charlie, Delta sequence",
            "Words correspond to letters A-Z",
        ],
        description="NATO standard: Alpha=A, Bravo=B, Charlie=C...",
        tags=["phonetic", "nato", "encoding", "communication"]),

    CipherEntry("C065", "Semaphore", "Encoding", "Modern",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "Flag positions encode letters",
            "Visual communication system",
        ],
        description="Flag semaphore signaling system.",
        tags=["visual", "flags", "semaphore"]),

    CipherEntry("C066", "Braille", "Encoding", "Modern",
        ioc_min=0.065, ioc_max=0.068,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "6-dot cells representing letters",
            "Binary pattern in 2×3 grid",
        ],
        description="Tactile writing system for visually impaired.",
        tags=["tactile", "braille", "encoding"]),

    # ── Special/Novelty ─────────────────────────────────────────────────────
    CipherEntry("C067", "Bacon's Cipher", "Steganographic", "Renaissance",
        ioc_min=0.038, ioc_max=0.042,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "Binary A/B encoding (AAAAA=A, AAAAB=B, etc.)",
            "Hidden in font variations (bold/italic)",
            "5-character groups",
        ],
        description="Francis Bacon's bilateral cipher using A/B alphabet.",
        tags=["steganographic", "bacon", "bilateral", "binary"]),

    CipherEntry("C068", "Polybius Checkerboard", "Classical", "Ancient",
        ioc_min=0.040, ioc_max=0.050,
        key_space="medium",
        frequency_flag=True,
        detection_rules=[
            "Pairs of digits 1-5",
            "Straddling checkerboard variant used in Soviet spies",
        ],
        description="Polybius square variant. Digits encode letter positions.",
        tags=["polybius", "checkerboard", "numeric"]),

    CipherEntry("C069", "Tap Code", "Classical", "Modern",
        ioc_min=0.040, ioc_max=0.052,
        key_space="small",
        frequency_flag=False,
        detection_rules=[
            "Pairs of taps (row, column) on 5×5 grid",
            "C and K share same cell",
            "Used by POWs in Vietnam War",
        ],
        description="Prison tap communication based on Polybius square.",
        tags=["taps", "polybius", "prison", "pow"]),

    CipherEntry("C070", "Nihilist Cipher", "Classical", "Modern",
        ioc_min=0.038, ioc_max=0.048,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "Polybius square + numeric key addition",
            "Two-digit codes range 11-55",
            "Russian nihilist revolutionaries used this",
        ],
        description="Polybius square + numeric keyword addition. Russian origin.",
        tags=["polybius", "nihilist", "russian", "numeric"]),

    CipherEntry("C071", "Trithemius Cipher", "Polyalphabetic", "Renaissance",
        ioc_min=0.042, ioc_max=0.055,
        key_space="small",
        frequency_flag=True,
        detection_rules=[
            "Autokey: key increments by 1 each position",
            "No external key needed",
            "Precursor to Vigenère",
        ],
        description="Progressive key cipher: each letter shifts one more than previous.",
        tags=["polyalphabetic", "trithemius", "progressive"]),

    CipherEntry("C072", "Porta Cipher", "Polyalphabetic", "Renaissance",
        ioc_min=0.042, ioc_max=0.058,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "26-letter key, 13 alphabets",
            "Reciprocal: same operation for encrypt/decrypt",
            "Weaker than Vigenère",
        ],
        description="Giovanni della Porta's reciprocal polyalphabetic cipher.",
        tags=["polyalphabetic", "porta", "reciprocal"]),

    CipherEntry("C073", "Vernam Cipher", "Modern", "Modern",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Basis of One-Time Pad concept",
            "XOR of plaintext with key",
            "Perfect secrecy when key is truly random and never reused",
        ],
        description="Gilbert Vernam's XOR cipher. With random key = OTP.",
        tags=["vernam", "xor", "otp", "perfect-secrecy"]),

    CipherEntry("C074", "Chaocipher", "Classical", "Modern",
        ioc_min=0.045, ioc_max=0.058,
        key_space="large",
        frequency_flag=True,
        detection_rules=[
            "Two disks with constantly evolving alphabets",
            "John F. Byrne's invention (1918)",
            "Algorithm kept secret until 2010",
        ],
        description="John Byrne's Chaocipher: evolving alphabet disks.",
        tags=["chaocipher", "evolving", "disk"]),

    CipherEntry("C075", "LFSR Stream Cipher", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.040,
        key_space="large",
        frequency_flag=False,
        detection_rules=[
            "Linear Feedback Shift Register output",
            "Berlekamp-Massey algorithm finds minimal LFSR",
            "Periodic — period = 2^n - 1 for n-bit LFSR",
        ],
        description="Linear Feedback Shift Register based stream cipher.",
        tags=["lfsr", "stream", "linear", "feedback"]),

    CipherEntry("C076", "PKZIP / ZIP Encryption", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="medium",
        frequency_flag=False,
        detection_rules=[
            "Known-plaintext attack possible (need 12 known bytes)",
            "CRC32 stored unencrypted — partial info leak",
            "PKcrack tool attacks this",
        ],
        description="Traditional ZIP encryption (ZipCrypto). Weak to known-plaintext.",
        tags=["zip", "pkzip", "legacy", "weak"]),

    CipherEntry("C077", "Signal Protocol", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Double Ratchet Algorithm",
            "X3DH key agreement",
            "Forward secrecy + break-in recovery",
            "Used by Signal, WhatsApp, iMessage",
        ],
        description="Double Ratchet E2E protocol. Gold standard for messaging.",
        tags=["signal", "double-ratchet", "e2e", "forward-secrecy"]),

    CipherEntry("C078", "Homomorphic Encryption", "Modern", "Contemporary",
        ioc_min=0.038, ioc_max=0.039,
        key_space="infinite",
        frequency_flag=False,
        detection_rules=[
            "Compute on encrypted data without decrypting",
            "Fully Homomorphic (FHE) vs Partial (PHE)",
            "BGV, BFV, CKKS schemes",
            "Very high computational overhead",
        ],
        description="Compute on ciphertext. FHE/PHE schemes (BGV, CKKS).",
        tags=["homomorphic", "fhe", "cloud-computing", "cutting-edge"]),
]

# ── CipherDB class ─────────────────────────────────────────────────────────────

class CipherDB:
    """In-memory cipher database with lookup, search, and filter capabilities."""

    def __init__(self):
        self._by_id: dict[str, CipherEntry] = {c.id: c for c in CIPHERS}
        self._by_name: dict[str, CipherEntry] = {c.name.lower(): c for c in CIPHERS}

    def get(self, cipher_id: str) -> Optional[CipherEntry]:
        return self._by_id.get(cipher_id.upper())

    def get_by_name(self, name: str) -> Optional[CipherEntry]:
        return self._by_name.get(name.lower())

    def all(self) -> List[CipherEntry]:
        return list(CIPHERS)

    def by_category(self, category: str) -> List[CipherEntry]:
        return [c for c in CIPHERS if c.category.lower() == category.lower()]

    def by_era(self, era: str) -> List[CipherEntry]:
        return [c for c in CIPHERS if c.era.lower() == era.lower()]

    def frequency_detectable(self) -> List[CipherEntry]:
        return [c for c in CIPHERS if c.frequency_flag]

    def by_ioc_range(self, ioc: float) -> List[CipherEntry]:
        """Return ciphers whose IoC range contains the given value."""
        return [c for c in CIPHERS if c.ioc_min <= ioc <= c.ioc_max]

    def search(self, query: str) -> List[CipherEntry]:
        """Search by name, tags, description."""
        q = query.lower()
        results = []
        for c in CIPHERS:
            if (q in c.name.lower() or
                q in c.description.lower() or
                any(q in t for t in c.tags) or
                q in c.category.lower()):
                results.append(c)
        return results

    def categories(self) -> List[str]:
        return sorted(set(c.category for c in CIPHERS))

    def stats(self) -> dict:
        from collections import Counter
        cats = Counter(c.category for c in CIPHERS)
        eras = Counter(c.era for c in CIPHERS)
        return {
            "total": len(CIPHERS),
            "categories": dict(cats),
            "eras": dict(eras),
            "frequency_detectable": sum(1 for c in CIPHERS if c.frequency_flag),
        }


# Singleton
cipher_db = CipherDB()
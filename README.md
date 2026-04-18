# vanity_wallet.py

Generate a Bitcoin Taproot (P2TR: `bc1p...`) vanity address for **Ordinals**, one that starts and/or ends with a string of your choice, and outputs a full **BIP39 mnemonic** ready to import directly into compatible wallets (Xverse, Leather, Sparrow). Runs entirely offline on your local CPU, no compilation required.

<p align="center">
  <img src="vanity_wallet.webp" alt="vanity_wallet" />
</p>

## Changelog

**v0.4**
- Added `TARGET_PREFIXANDSUFFIX` parameter: search for pairs `[prefix, suffix]` where both must match simultaneously (AND logic per pair)
- Multiple pairs are supported (OR logic between pairs) — the first address matching any pair wins
- Probability calculation and checkpoint tracking updated accordingly

**v0.3**
- Added `TARGET_NOPREF` parameter: search for a pattern at the start or end simultaneously
- Returns the first match regardless of position (prefix or suffix)
- Reduces average search time by ~2x compared to prefix-only or suffix-only for the same word

**v0.2**
- Added multi-pattern search support
- Allows multiple prefix and/or suffix patterns
- Stops on first successful match
- Supports patterns of varying lengths

---

## ⚠️ Disclaimer & Security Recommendations

**Use this script at your own risk.** It handles sensitive cryptographic material (private keys derived from a mnemonic). The author takes no responsibility for lost funds, stolen keys, or any misuse.

**Strongly recommended practices:**

- **Run offline.** Disable Wi-Fi and unplug ethernet before running the script. A mnemonic generated on an internet-connected machine is a mnemonic at risk.
- **Shred, don't just delete, the result file.** After noting your mnemonic, use a file-shredding tool (e.g. [Eraser](https://eraser.heidi.ie/) on Windows, `shred` on Linux, Secure Empty Trash on macOS) to overwrite the clusters before deletion. A normal delete leaves the data recoverable.
- **Reboot after noting the mnemonic.** Warning: RAM is not guaranteed to be wiped on shutdown. To purge sensitive data, fully power off the system and disconnect it from all power sources for at least 2 minutes before restarting.
- **Enable pagefile clearing on shutdown (Windows).** Windows may swap RAM content to `pagefile.sys`. To auto-wipe it: open `regedit`, navigate to `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management`, and set `ClearPageFileAtShutdown` to `1`.
- **Write the mnemonic on paper, not in a digital file.** If you must store it digitally, use an encrypted, air-gapped solution (e.g. VeraCrypt container on an offline drive).
- **Never share the mnemonic or the result JSON** with anyone or any service. Anyone with access to this data can take full control of your funds.
- **The `.gitignore` file is not a security guarantee.** It helps prevent accidental inclusion of sensitive files when using `git add`, but it does not guarantee protection if files are manually added or are already tracked by Git.
- **None of the above matters on a compromised machine.** If your system is already infected with a keylogger or trojan, any mnemonic you type, display, or save is potentially exposed regardless of all other precautions. For maximum security, run the script on a freshly installed OS with no network access, or on a dedicated air-gapped machine.

---

## Limitations

### Valid characters

Bitcoin `bc1p` addresses use the **bech32m** alphabet. Only the following 32 characters are valid for your vanity pattern:

```
q p z r y 9 x 8 g f 2 t v d w 0 s 3 j n 5 4 k h c e 6 m u a 7 l
```

The following characters are **excluded** (visual ambiguity): `b`, `i`, `o`, `1`, and all uppercase letters.

### Ordinals address, not the payment address

The vanity pattern applies to the **Ordinals / P2TR address** (`bc1p...`), which is the one used to receive and hold inscriptions. The script also derives the companion payment address (`bc1q...`) for reference, but no vanity constraint is applied to it.

### Expected search time

The table below shows **average** expected times (you may finish much sooner or later):

Estimates assume **~150/s per core** (measured on a typical desktop CPU). Total throughput scales linearly with core count.

| Pattern type | Characters | Expected attempts | 4-core (~600/s total) | 16-core (~2,400/s total) |
|---|---|---|---|---|
| Prefix only | 4 | ~1 million | ~30 min | ~7 min |
| Prefix only | 5 | ~33 million | ~15 h | ~4 h |
| Suffix only | 4 | ~1 million | ~30 min | ~7 min |
| Suffix only | 5 | ~33 million | ~15 h | ~4 h |
| Prefix **+** Suffix | 4+4 | ~1 billion | ~21 days | ~5 days |
| Prefix **+** Suffix | 5+5 | ~1.1 trillion | ~58 years | ~14 years |

> The combined prefix+suffix mode is provided for completeness. In practice, anything above 4+4 is not realistic on consumer hardware.

### Compatible wallets

The generated mnemonic uses standard **BIP39** with **BIP86** derivation (`m/86'/0'/0'/0/0`) for the `bc1p` address and **BIP84** (`m/84'/0'/0'/0/0`) for the `bc1q` address. It is compatible with any wallet that supports BIP86 P2TR import, including:

- **[Xverse](https://xverse.app/)** - import as a new standalone wallet
- **[Leather (Hiro)](https://leather.io/)** - supports BIP86 for Ordinals
- **[Sparrow Wallet](https://sparrowwallet.com/)** - full BIP86 desktop wallet

> **UniSat** is generally not recommended for vanity wallets: its address model may not expose arbitrary BIP86 derivation indices directly, making import unreliable.

---

## Prerequisites

- **Python 3.8+**
- **bip_utils**

```bash
pip install bip_utils
```

---

## Usage

### 1. Configure your target

Open `vanity_wallet.py` and edit the `CONFIG` section at the top:

```python
TARGET_PREFIX = ["dead", "cafe"]    # list of prefixes (bc1p[prefix]...); [] = disabled
TARGET_SUFFIX = []                  # list of suffixes (bc1p...[suffix]); [] = disabled
TARGET_NOPREF = []                  # list of patterns to match at start OR end (first found wins); [] = disabled
```

Set at least one non-empty list. The script stops as soon as **any** pattern is matched -- searching for multiple patterns runs in parallel at no extra cost and reduces expected time proportionally. For example, 3 prefixes of the same length find a result ~3x faster on average than a single prefix.

### 2. Run the script

```bash
python vanity_wallet.py
```

At startup, the script benchmarks your CPU and displays an ETA:

```
=================================================================
  vanity_wallet.py -- Bitcoin bc1p vanity address generator
=================================================================

  Target          : bc1p[dead]...
  Expected tries  : 1,048,576  (32^4)
  Workers         : 8 cores
  Mnemonic        : 12 words

  Benchmark (30 derivations on 1 core)...
  Speed           : 45/s/core  ->  360/s total
  ETA             : ~39 min  (~0.7h)

  Auto checkpoint : every 60s
  Clean stop      : Ctrl+C  (counter will be saved)

  Starting...
```

### 3. Stop and resume (checkpoint system)

Press **Ctrl+C** at any time for a clean stop. The current attempt counter is saved to `vanity_wallet_checkpoint.json`. Simply re-run the script the next day and it will resume from where it left off and display an adjusted ETA:

```
  [RESUMED] Session 2
  Already done    : 8,450,000 attempts (25.5% of expected)
  ETA remaining   : ~367 min  (~6.1h)
```

> The checkpoint tracks the **counter only**, not attempted mnemonics. Since the mnemonic space is ~2¹²⁸, the probability of generating a duplicate across sessions is negligible to the point of being cryptographically irrelevant, even running all the world's computers for the age of the universe would not make it likely.

### 4. Result

When a match is found, the mnemonic and addresses are displayed in the terminal and saved to `vanity_wallet_result.json`:

```
=================================================================
  FOUND in 18432s  (2,750,000 attempts this session)
  Total           : 11,200,000 attempts over 2 session(s)
  Target          : bc1p[dead]...
=================================================================

  bc1p (ordinals)  : bc1pdead...
  bc1q (payments)  : bc1q...

  Mnemonic (12 words):
     1. word1
     ...
    12. word12

=================================================================
  IMPORTANT:
  1. Write down the mnemonic above before doing anything else
  2. Shred vanity_wallet_result.json (use a file-shredding tool, not a simple delete)
  3. Import the mnemonic into your wallet as a new standalone seed
=================================================================
```

### 5. After import

1. **Shred** `vanity_wallet_result.json` with a file-shredding tool
2. Import the mnemonic into your wallet as a **new standalone seed** (not mixed with an existing wallet)
3. **Reboot** your machine to clear RAM
4. Delete `vanity_wallet_checkpoint.json` (no longer needed)

---

## Output files

| File | Purpose | Delete when? |
|---|---|---|
| `vanity_wallet_result.json` | Mnemonic + addresses | Shred **Immediately** after noting your mnemonic |
| `vanity_wallet_checkpoint.json` | Resume counter between sessions | Delete after the address is found |

> Both files are saved directly to your **Desktop** (`~/Desktop`) on Windows/MacOs/Linux regardless of where the script is run from, so they are always easy to locate.

#!/usr/bin/env python3
"""
vanity_wallet.py
Generates a Bitcoin Taproot P2TR (bc1p...) vanity wallet whose address starts and/or ends
with a chosen string. Uses all CPU cores via multiprocessing
(PBKDF2-HMAC-SHA512 is not GPU-friendly).

Can be used:
  - CLI: python vanity_wallet.py  (reads CONFIG block below)
  - As a module: from vanity_wallet import run; run(config, progress_cb, stop_event)

Dependency: pip install bip_utils
"""

import os
import sys
import time
import json
import signal
import multiprocessing
from pathlib import Path

# ---------------------------------------------------------------------------
#  CONFIG  (CLI mode only — UI mode receives config via run())
# ---------------------------------------------------------------------------
TARGET_PREFIX          = []  # list of prefixes (bc1p[prefix]...); [] = disabled
TARGET_SUFFIX          = []                        # list of suffixes (bc1p...[suffix]); [] = disabled
TARGET_NOPREF          = []  # list of patterns to match at start OR end (first found wins); [] = disabled
TARGET_PREFIXANDSUFFIX = [["dead", "cafe"]]                    # list of [prefix, suffix] pairs (AND per pair, OR between pairs); [] = disabled
WALLET_INDEX  = 0              # BIP86 m/86'/0'/0'/0/{index} -- 0 = first wallet
PASSPHRASE    = ""             # BIP39 passphrase (leave empty = none)
WORDS_COUNT   = 12             # 12 or 24 words (12 = 128 bits, sufficient)
WORKERS       = None           # None = os.cpu_count()
_DESKTOP            = Path.home() / "Desktop"
OUTPUT_FILE         = _DESKTOP / "vanity_wallet_result.json"
CHECKPOINT_FILE     = _DESKTOP / "vanity_wallet_checkpoint.json"
CHECKPOINT_INTERVAL = 60       # seconds between automatic checkpoint saves
# ---------------------------------------------------------------------------

BECH32M_CHARSET = set("qpzry9x8gf2tvdw0s3jn54khce6mua7l")


# ---------------------------------------------------------------------------
#  CHECKPOINT
# ---------------------------------------------------------------------------

def _load_checkpoint():
    """Load checkpoint if it matches the current target.
    Returns (prev_attempts, prev_sessions)."""
    path = Path(CHECKPOINT_FILE)
    if not path.exists():
        return 0, 0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if (data.get("target_prefix") != TARGET_PREFIX or
                data.get("target_suffix") != TARGET_SUFFIX or
                data.get("target_nopref") != TARGET_NOPREF or
                data.get("target_prefixandsuffix") != TARGET_PREFIXANDSUFFIX):
            print(f"  [CHECKPOINT] Different target in checkpoint -- ignored."
                  f" (prefix={data.get('target_prefix')!r} suffix={data.get('target_suffix')!r}"
                  f" nopref={data.get('target_nopref')!r} prefixandsuffix={data.get('target_prefixandsuffix')!r})")
            return 0, 0
        if data.get("found"):
            label = _target_label()
            print(f"\n  [CHECKPOINT] Target '{label}' was already found")
            print(f"  in a previous session.")
            print(f"  Result file: {OUTPUT_FILE}")
            print(f"  Delete or rename the checkpoint file to start a new search.\n")
            sys.exit(0)
        prev = int(data.get("total_attempts", 0))
        sess = int(data.get("sessions", 0))
        return prev, sess
    except Exception as e:
        print(f"  [CHECKPOINT] Could not read checkpoint ({e}) -- starting from scratch.")
        return 0, 0


def _save_checkpoint(total_attempts, sessions, found=False):
    """Save checkpoint to disk."""
    data = {
        "target_prefix":          TARGET_PREFIX,
        "target_suffix":          TARGET_SUFFIX,
        "target_nopref":          TARGET_NOPREF,
        "target_prefixandsuffix": TARGET_PREFIXANDSUFFIX,
        "total_attempts": total_attempts,
        "sessions":       sessions,
        "last_saved":     time.strftime("%Y-%m-%dT%H:%M:%S"),
        "found":          found,
        "NOTE":           "Delete this file to start a new search from scratch.",
    }
    try:
        with open(CHECKPOINT_FILE, 'w', encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"\n  [WARNING] Checkpoint save failed: {e}")


# ---------------------------------------------------------------------------


def _target_label():
    """Return a human-readable description of the current target."""
    pfxs  = [p for p in TARGET_PREFIX if p]
    sfxs  = [s for s in TARGET_SUFFIX if s]
    npfs  = [p for p in TARGET_NOPREF if p]
    pairs = [p for p in TARGET_PREFIXANDSUFFIX if p and len(p) == 2]
    parts = []
    if pfxs:
        parts.append("bc1p[" + "|".join(pfxs) + "]...")
    if sfxs:
        parts.append("bc1p...[" + "|".join(sfxs) + "]")
    if npfs:
        parts.append("[" + "|".join(npfs) + "](either end)")
    if pairs:
        parts.append("|".join(f"bc1p[{p[0]}]...[{p[1]}]" for p in pairs))
    return "  |  ".join(parts) if parts else "(none)"


def _worker(target_prefixes, target_suffixes, target_nopref, target_prefixandsuffix,
            passphrase, wallet_index, words_count,
            stop_event, result_queue, counter,
            only_digits=False, only_letters=False):
    """Worker: generates random mnemonics and checks bc1p against all prefix/suffix patterns."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # workers ignore Ctrl+C
    _DIGITS  = set('023456789')         # bech32m digits (1 excluded)
    _LETTERS = set('qpzryx gftvdwsjnkhcemuаl') - {' '}  # placeholder — set below
    _LETTERS = set('qpzryx8gf2tvdw0s3jn54khce6mua7l') - _DIGITS
    from bip_utils import (
        Bip39MnemonicGenerator, Bip39WordsNum,
        Bip39SeedGenerator, Bip86, Bip86Coins, Bip44Changes,
        Bip84, Bip84Coins,
    )

    wn_map = {
        12: Bip39WordsNum.WORDS_NUM_12,
        15: Bip39WordsNum.WORDS_NUM_15,
        18: Bip39WordsNum.WORDS_NUM_18,
        21: Bip39WordsNum.WORDS_NUM_21,
        24: Bip39WordsNum.WORDS_NUM_24,
    }
    words_num = wn_map.get(words_count, Bip39WordsNum.WORDS_NUM_12)
    mnemonic_gen = Bip39MnemonicGenerator()

    local = 0
    while not stop_event.is_set():
        mnemonic     = mnemonic_gen.FromWordsNumber(words_num)
        seed         = Bip39SeedGenerator(mnemonic).Generate(passphrase)

        # bc1p address (BIP86 P2TR)
        bc1p = (
            Bip86.FromSeed(seed, Bip86Coins.BITCOIN)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(wallet_index)
            .PublicKey().ToAddress()
        )

        local += 1
        if local % 50 == 0:
            with counter.get_lock():
                counter.value += 50

        # Prefix/suffix patterns (OR logic: match any prefix OR any suffix independently)
        prefix_match = bool(target_prefixes) and any(bc1p.startswith("bc1p" + p) for p in target_prefixes)
        suffix_match = bool(target_suffixes) and any(bc1p.endswith(s) for s in target_suffixes)
        combined_match = prefix_match or suffix_match
        # No-preference patterns (OR logic: match at start OR end)
        nopref_match = bool(target_nopref) and any(
            bc1p.startswith("bc1p" + w) or bc1p.endswith(w) for w in target_nopref
        )
        # Prefix-AND-suffix pairs (each pair requires both prefix AND suffix; OR between pairs)
        pnsuf_match = bool(target_prefixandsuffix) and any(
            bc1p.startswith("bc1p" + pair[0]) and bc1p.endswith(pair[1])
            for pair in target_prefixandsuffix
        )
        match = combined_match or nopref_match or pnsuf_match
        # Whole-address character-set checks (every char of bc1p[4:] must be in set)
        addr_body = bc1p[4:]  # strip "bc1p"
        charset_match = False
        if not match and only_digits  and all(c in _DIGITS  for c in addr_body):
            match = True
            charset_match = True
        if not match and only_letters and all(c in _LETTERS for c in addr_body):
            match = True
            charset_match = True

        if match:
            if charset_match:
                matched_prefix, matched_suffix = '', ''
            else:
                matched_prefix = next((p for p in target_prefixes if bc1p.startswith("bc1p" + p)), "")
                matched_suffix = next((s for s in target_suffixes if bc1p.endswith(s)), "")
                if not matched_prefix and not matched_suffix and nopref_match:
                    # matched via TARGET_NOPREF -- find which word and which end
                    w = next((w for w in target_nopref if bc1p.startswith("bc1p" + w) or bc1p.endswith(w)), "")
                    if bc1p.startswith("bc1p" + w):
                        matched_prefix = w
                    else:
                        matched_suffix = w
                if not matched_prefix and not matched_suffix and pnsuf_match:
                    # matched via TARGET_PREFIXANDSUFFIX
                    pair = next(
                        (pr for pr in target_prefixandsuffix
                         if bc1p.startswith("bc1p" + pr[0]) and bc1p.endswith(pr[1])), None
                    )
                    if pair:
                        matched_prefix, matched_suffix = pair[0], pair[1]
            # Also derive bc1q for reference
            bc1q = (
                Bip84.FromSeed(seed, Bip84Coins.BITCOIN)
                .Purpose().Coin().Account(0)
                .Change(Bip44Changes.CHAIN_EXT)
                .AddressIndex(wallet_index)
                .PublicKey().ToAddress()
            )
            stop_event.set()
            result_queue.put({
                "mnemonic":       mnemonic.ToStr(),
                "bc1p":           bc1p,
                "bc1q":           bc1q,
                "matched_prefix": matched_prefix,
                "matched_suffix": matched_suffix,
            })
            return


def _benchmark(passphrase, wallet_index, words_count, n=30):
    """Measure the derivation speed on one core."""
    from bip_utils import (
        Bip39MnemonicGenerator, Bip39WordsNum,
        Bip39SeedGenerator, Bip86, Bip86Coins, Bip44Changes,
    )
    wn_map = {
        12: Bip39WordsNum.WORDS_NUM_12,
        24: Bip39WordsNum.WORDS_NUM_24,
    }
    words_num    = wn_map.get(words_count, Bip39WordsNum.WORDS_NUM_12)
    mnemonic_gen = Bip39MnemonicGenerator()
    t = time.time()
    for _ in range(n):
        m    = mnemonic_gen.FromWordsNumber(words_num).ToStr()
        seed = Bip39SeedGenerator(m).Generate(passphrase)
        (
            Bip86.FromSeed(seed, Bip86Coins.BITCOIN)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(wallet_index)
            .PublicKey().ToAddress()
        )
    return n / (time.time() - t)


def main():
    # --- Validation ---
    prefixes = [p for p in TARGET_PREFIX if p]
    suffixes = [s for s in TARGET_SUFFIX if s]
    nopref   = [w for w in TARGET_NOPREF if w]
    pairs    = [p for p in TARGET_PREFIXANDSUFFIX if p and len(p) == 2 and p[0] and p[1]]
    if not prefixes and not suffixes and not nopref and not pairs:
        sys.exit("[ERROR] All TARGET_PREFIX, TARGET_SUFFIX, TARGET_NOPREF and TARGET_PREFIXANDSUFFIX are empty.")
    pair_chars = [c for pair in pairs for part in pair for c in part]
    invalid = [c for c in "".join(prefixes + suffixes + nopref) + "".join(pair_chars) if c not in BECH32M_CHARSET]
    if invalid:
        sys.exit(
            f"[ERROR] Invalid bech32m characters: {''.join(sorted(set(invalid)))}\n"
            f"Allowed characters: {''.join(sorted(BECH32M_CHARSET))}\n"
            f"Excluded (visual confusion): b i o 1 and uppercase"
        )

    n_workers  = WORKERS or os.cpu_count()
    n_patterns = len(prefixes) + len(suffixes) + len(nopref) + len(pairs)
    p_combined = sum(1.0 / 32**len(p) for p in prefixes) + sum(1.0 / 32**len(s) for s in suffixes)
    p_nopref = sum(2.0 / 32**len(w) for w in nopref)
    p_pairs  = sum(1.0 / 32**len(pr[0]) * (1.0 / 32**len(pr[1])) for pr in pairs)
    p_total  = p_combined + p_nopref + p_pairs
    expected = int(1 / p_total) if p_total > 0 else 10**18

    # --- Load checkpoint ---
    prev_attempts, prev_sessions = _load_checkpoint()

    print(f"\n{'='*65}")
    print(f"  vanity_wallet.py -- Bitcoin bc1p vanity address generator")
    print(f"{'='*65}")
    print(f"\n  Target          : {_target_label()}")
    print(f"  Patterns        : {n_patterns}  ({len(prefixes)} prefix, {len(suffixes)} suffix, {len(nopref)} either, {len(pairs)} prefix+suffix)")
    print(f"  Expected tries  : {expected:,}")
    print(f"  Workers         : {n_workers} cores")
    print(f"  Mnemonic        : {WORDS_COUNT} words")
    if prev_attempts > 0:
        pct_done = prev_attempts / expected * 100
        print(f"\n  [RESUMED] Session {prev_sessions + 1}")
        print(f"  Already done    : {prev_attempts:,} attempts ({pct_done:.1f}% of expected)")
    print(f"\n  Benchmark ({30} derivations on 1 core)...")
    rate_1 = _benchmark(PASSPHRASE, WALLET_INDEX, WORDS_COUNT, 30)
    rate_n = rate_1 * n_workers
    eta_total_s = expected / rate_n
    remaining   = max(expected, expected - prev_attempts)  # at least 1 full cycle if exceeded
    remaining   = expected - prev_attempts if prev_attempts < expected else expected
    eta_rest_s  = remaining / rate_n if rate_n > 0 else 0
    print(f"  Speed           : {rate_1:.0f}/s/core  ->  {rate_n:,.0f}/s total")
    if prev_attempts == 0:
        print(f"  ETA             : ~{eta_total_s/60:.0f} min  (~{eta_total_s/3600:.1f}h)")
    elif prev_attempts < expected:
        print(f"  ETA remaining   : ~{eta_rest_s/60:.0f} min  (~{eta_rest_s/3600:.1f}h)")
        print(f"  ETA total       : ~{eta_total_s/3600:.1f}h  ({prev_attempts/rate_n/3600:.1f}h already done)")
    else:
        print(f"  ETA             : ~{eta_total_s/60:.0f} min  (past expected count, in the long tail)")
    print(f"\n  Auto checkpoint : every {CHECKPOINT_INTERVAL}s")
    print(f"  Clean stop      : Ctrl+C  (counter will be saved)")
    print(f"\n  Starting...\n")

    stop_event   = multiprocessing.Event()
    result_queue = multiprocessing.Queue()
    counter      = multiprocessing.Value('q', 0)

    procs = [
        multiprocessing.Process(
            target=_worker,
            args=(prefixes, suffixes, nopref, pairs, PASSPHRASE, WALLET_INDEX, WORDS_COUNT,
                  stop_event, result_queue, counter),
            daemon=True,
        )
        for _ in range(n_workers)
    ]

    t0        = time.time()
    last_ckpt = t0
    for p in procs:
        p.start()

    try:
        while not stop_event.is_set():
            time.sleep(5)
            now     = time.time()
            elapsed = now - t0
            count   = counter.value
            total   = prev_attempts + count
            rate    = count / elapsed if elapsed > 0 else 0
            # ETA: if we exceeded expected count, reset display to 1 full cycle
            remaining_display = (expected - total) if total < expected else expected
            eta     = remaining_display / rate / 60 if rate > 0 else 0
            pct     = total / expected * 100
            flag    = "  " if total < expected else ">>"  # '>>' = past 100%, long tail
            print(f"  {total:>12,} attempts  |  {rate:>8,.0f}/s  |  "
                  f"{flag}{pct:5.1f}%  |  ETA ~{eta:.0f} min    ", end='\r')
            # Periodic checkpoint save
            if now - last_ckpt >= CHECKPOINT_INTERVAL:
                _save_checkpoint(total, prev_sessions + 1)
                last_ckpt = now
    except KeyboardInterrupt:
        count = counter.value
        total = prev_attempts + count
        _save_checkpoint(total, prev_sessions + 1)
        elapsed = time.time() - t0
        pct = total / expected * 100
        print(f"\n\n  [STOPPED] User interrupted after {elapsed:.0f}s")
        print(f"  Total attempts  : {total:,} ({pct:.1f}% of expected)")
        print(f"  Checkpoint saved: {Path(CHECKPOINT_FILE).resolve()}")
        print(f"  Re-run the script to resume.")
        stop_event.set()
        sys.exit(0)

    for p in procs:
        p.join(timeout=3)

    elapsed = time.time() - t0
    count   = counter.value
    total   = prev_attempts + count
    result  = result_queue.get()

    # --- Save final checkpoint (found=True) ---
    _save_checkpoint(total, prev_sessions + 1, found=True)

    # --- Display result ---
    print(f"\n\n{'='*65}")
    print(f"  FOUND in {elapsed:.0f}s  ({count:,} attempts this session)")
    print(f"  Total           : {total:,} attempts over {prev_sessions + 1} session(s)")
    print(f"  Target          : {_target_label()}")
    print(f"{'='*65}")
    print(f"\n  bc1p (ordinals)  : {result['bc1p']}")
    print(f"  bc1q (payments)  : {result['bc1q']}")
    if n_patterns > 1:
        mp  = result.get('matched_prefix', '')
        ms  = result.get('matched_suffix', '')
        lbl = ("bc1p[" + mp + "]" if mp else "bc1p") + "..." + ("[" + ms + "]" if ms else "")
        print(f"  Matched pattern  : {lbl}")
    print(f"\n  Mnemonic ({WORDS_COUNT} words):")
    words = result['mnemonic'].split()
    for i, w in enumerate(words, 1):
        print(f"    {i:>2}. {w}")
    print(f"\n{'='*65}")
    print(f"  IMPORTANT:")
    print(f"  1. Write down the mnemonic above before doing anything else")
    print(f"  2. Shred {Path(OUTPUT_FILE).name} (use a file-shredding tool, not a simple delete)")
    print(f"  3. Import the mnemonic into your wallet as a new standalone seed")
    print(f"{'='*65}\n")

    # --- Temporary result save ---
    out = {
        "bc1p":           result["bc1p"],
        "bc1q":           result["bc1q"],
        "mnemonic":       result["mnemonic"],
        "matched_prefix": result.get("matched_prefix", ""),
        "matched_suffix": result.get("matched_suffix", ""),
        "wallet_index":   WALLET_INDEX,
        "words":        WORDS_COUNT,
        "attempts":     total,
        "elapsed_s":    round(elapsed, 1),
        "WARNING":      "SHRED THIS FILE (do not just delete) after importing the mnemonic into your wallet",
    }
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"  Temporary save: {Path(OUTPUT_FILE).resolve()}")


# ---------------------------------------------------------------------------
#  MODULE ENTRY POINT  (called by app.py / UI)
# ---------------------------------------------------------------------------

def run(config, progress_cb=None, stop_event=None):
    """
    Run a vanity search with a config dict.  Can be called from app.py.

    config keys:
        prefixes            list[str]
        suffixes            list[str]
        nopref              list[str]
        pairs               list[[str,str]]
        passphrase          str
        wallet_index        int
        words_count         int  (12 or 24)
        workers             int|None
        checkpoint_file     str|Path|None
        checkpoint_interval int  (seconds)

    progress_cb(event_dict) — called periodically and on completion.
    stop_event — threading.Event or multiprocessing.Event; set it to abort.

    Returns the result dict on success, or None if stopped before a match.
    """
    import threading

    prefixes   = [p for p in config.get("prefixes", []) if p]
    suffixes   = [s for s in config.get("suffixes", []) if s]
    nopref     = [w for w in config.get("nopref", []) if w]
    pairs      = [p for p in config.get("pairs", []) if p and len(p) == 2 and p[0] and p[1]]
    passphrase = config.get("passphrase", "")
    wallet_index = int(config.get("wallet_index", 0))
    words_count  = int(config.get("words_count", 12))
    n_workers    = config.get("workers") or os.cpu_count()
    ckpt_file    = Path(config["checkpoint_file"]) if config.get("checkpoint_file") else None
    ckpt_interval = int(config.get("checkpoint_interval", 60))

    only_digits  = bool(config.get("only_digits",  False))
    only_letters = bool(config.get("only_letters", False))

    # probability / expected
    p_combined = sum(1.0 / 32**len(p) for p in prefixes) + sum(1.0 / 32**len(s) for s in suffixes)
    p_nopref_  = sum(2.0 / 32**len(w) for w in nopref)
    p_pairs_   = sum(1.0 / 32**len(pr[0]) * (1.0 / 32**len(pr[1])) for pr in pairs)
    p_total    = p_combined + p_nopref_ + p_pairs_
    # Add only_digits / only_letters to probability estimate
    _DIGITS_SET  = set('023456789')
    _LETTERS_SET = set('qpzryx8gf2tvdw0s3jn54khce6mua7l') - _DIGITS_SET
    ADDR_LEN = 58  # bc1p address body length (after 'bc1p')
    if only_digits:
        p_total += (len(_DIGITS_SET)  / 32) ** ADDR_LEN
    if only_letters:
        p_total += (len(_LETTERS_SET) / 32) ** ADDR_LEN
    expected   = int(1 / p_total) if p_total > 0 else 10**18

    # checkpoint
    prev_attempts, prev_sessions = 0, 0
    if ckpt_file and ckpt_file.exists():
        try:
            with open(ckpt_file, encoding="utf-8") as f:
                ck = json.load(f)
            if (ck.get("prefixes") == prefixes and ck.get("suffixes") == suffixes
                    and ck.get("nopref") == nopref and ck.get("pairs") == pairs
                    and not ck.get("found")):
                prev_attempts = int(ck.get("total_attempts", 0))
                prev_sessions = int(ck.get("sessions", 0))
        except Exception:
            pass

    def _save_ckpt(total, sessions, found=False):
        if not ckpt_file:
            return
        try:
            with open(ckpt_file, 'w', encoding="utf-8") as f:
                json.dump({
                    "prefixes": prefixes, "suffixes": suffixes,
                    "nopref": nopref, "pairs": pairs,
                    "total_attempts": total, "sessions": sessions,
                    "expected": expected,
                    "last_saved": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "found": found,
                }, f, indent=2)
        except Exception:
            pass

    # benchmark
    rate_1 = _benchmark(passphrase, wallet_index, words_count, 20)
    rate_n = rate_1 * n_workers

    if progress_cb:
        progress_cb({
            "type": "start",
            "expected": expected,
            "rate": round(rate_n),
            "prev_attempts": prev_attempts,
            "prev_sessions": prev_sessions,
            "workers": n_workers,
        })

    mp_stop  = multiprocessing.Event()
    rq       = multiprocessing.Queue()
    counter  = multiprocessing.Value('q', 0)

    # honour external stop_event via a bridge thread
    if stop_event is not None:
        def _bridge():
            while not stop_event.is_set() and not mp_stop.is_set():
                time.sleep(0.25)
            mp_stop.set()
        threading.Thread(target=_bridge, daemon=True).start()

    procs = [
        multiprocessing.Process(
            target=_worker,
            args=(prefixes, suffixes, nopref, pairs, passphrase, wallet_index,
                  words_count, mp_stop, rq, counter),
            kwargs={"only_digits": only_digits, "only_letters": only_letters},
            daemon=True,
        )
        for _ in range(n_workers)
    ]
    t0 = time.time()
    last_ckpt = t0
    for p in procs:
        p.start()

    result = None
    try:
        while not mp_stop.is_set():
            time.sleep(2)
            now     = time.time()
            elapsed = now - t0
            count   = counter.value
            total   = prev_attempts + count
            rate    = count / elapsed if elapsed > 0 else rate_n
            remaining = max(0, expected - total)
            eta_s   = remaining / rate if rate > 0 else 0
            pct     = total / expected * 100

            if progress_cb:
                progress_cb({
                    "type":     "progress",
                    "total":    total,
                    "rate":     round(rate),
                    "pct":      round(pct, 1),
                    "eta_s":    round(eta_s),
                    "elapsed_s": round(elapsed),
                })

            if now - last_ckpt >= ckpt_interval:
                _save_ckpt(total, prev_sessions + 1)
                last_ckpt = now

            if not rq.empty():
                result = rq.get_nowait()
                mp_stop.set()
                break
    except Exception:
        mp_stop.set()

    for p in procs:
        p.join(timeout=3)

    # drain queue in case result arrived during shutdown
    if result is None and not rq.empty():
        result = rq.get_nowait()

    if result is not None:
        count   = counter.value
        total   = prev_attempts + count
        elapsed = time.time() - t0
        _save_ckpt(total, prev_sessions + 1, found=True)
        result["attempts"]  = total
        result["sessions"]  = prev_sessions + 1
        result["elapsed_s"] = round(elapsed, 1)
        result["words_count"]   = words_count
        result["wallet_index"]  = wallet_index
        if progress_cb:
            progress_cb({"type": "found", "result": result})
        return result

    # stopped without finding
    count = counter.value
    total = prev_attempts + count
    _save_ckpt(total, prev_sessions + 1)
    if progress_cb:
        progress_cb({"type": "stopped", "total": total})
    return None


if __name__ == "__main__":
    main()

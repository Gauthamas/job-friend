"""Specificity and story screen for writing samples (plain counts, no model, prints numbers only).
Usage: python generic_check.py file1.txt file2.md ...      (add --show to print story windows)
Files may start with 'kind:' and 'register:' header lines; those are skipped.
Bands (calibrated on 20 sentences you labelled by hand; treat as a screen, not a score):
  concrete = named employer/project/credential AND a number, OR a metric (before-to-after, %, ms, lakh...)
  medium   = a name, OR a number, OR a tool/technology name
  generic  = none of those
  generic_carry = generic, unless the sentence before it (same paragraph) was anchored (a story continues)
Story markers, per 3-sentence window in one paragraph (a hypothesis, not yet validated):
  personal story = I/my + an anchor + (a reason, a contrast or a feeling) + an outcome
  worked example = an example cue ('let us', 'for example', 'we have taken') + an anchor
Edit NAMED and TECH to match your own history."""
import glob, os, re, sys

NAMED = r"\b(Acme Corp|Globex|Initech|Umbrella Corp|Hooli|Soylent|Vandelay|IBM|Kaggle)\b"
TECH = r"\b(Kotlin|Java|Jetpack|Retrofit|OkHttp|Dagger|Hilt|Room|Firebase|Gradle|MVVM|MVP|Coroutines?|Espresso|JUnit|Mockito|Jenkins|Circle ?CI|Crashlytics|New Relic|Dialogflow|Flutter|Glide|SQLite|Git|YAML|OpenGL|Material Design)\b"
METRIC = r"from [\d.]+%? to [\d.]+|\b\d+(\.\d+)?%|\bhours to\b|\b\d+\s?ms\b|\b\d+\+? ?lakh|\b\d+,\d{3}\b|\b\d+ to \d+\b"
CAUSE = r"\b(because|since|so that|so I|so we|which meant|as a result|therefore|to tackle|to fix|to solve|in order to|that's why|due to|which is why)\b"
CONTRAST = r"\b(but|however|although|though|instead|unfortunately|didn't|couldn't|wasn't|not only)\b"
FEELING = r"\b(tensed|worried|afraid|nervous|frustrat\w+|confus\w+|surpris\w+|struggl\w+|realis\w+|realiz\w+|learn(?:ed|t)|felt|enjoy\w*|loved|hated|annoy\w+|tension|stressed|proud)\b"
OUTCOME = r"\b(helped|reduced|improved|increased|decreased|cut|saved|faster|led to|resulted|results in|achieved|raised|grew|went from|boosted|eliminated|fixed)\b|from [\d.]+%? to [\d.]+"
EXAMPLE = r"\b(for example|for instance|e\.g\.|let us|let's|we have taken|we are using|consider|suppose|imagine)\b"
SKIP = re.compile(r"@|github\.com|\(91\)|^Cover Letter$|^Sincerely|^Dear |^---|^(kind|register)\s*:", re.I)
YEARS = re.compile(r"\b(over |more than |at least )?\d+\+?\s*(years?|yrs?)\b", re.I)
OPENER = re.compile(r"^I (have (extensive|strong|deep|proven|good|hands-on|experience)|understand|am (proficient|good|familiar|confident)|know\b|excel|consistently|stay|work well|can\b|believe|focus|always)", re.I)
FLATTER = re.compile(r"^Your\b|\b(aligns?|resonates?|excites? me|excited|drawn to|perfectly|ideal)\b", re.I)

def paragraphs(path):
    paras, cur = [], []
    def flush():
        nonlocal cur
        if cur:
            text = re.sub(r"\s+", " ", " ".join(cur))
            ss = [x for x in re.split(r"(?<=[.!?])\s+(?=[A-Z“\"])", text) if len(x.split()) >= 4]
            if ss: paras.append(ss)
            cur = []
    for ln in open(path, encoding="utf-8", errors="ignore").read().splitlines():
        s = ln.strip()
        if not s: flush(); continue
        if SKIP.search(s) or s.startswith("#") or re.match(r"^[-*•]\s", s): flush(); continue
        s = s.replace("**", "").replace("`", "")
        if len(s.split()) <= 7 and not re.search(r"[.!?]$", s): flush(); continue
        cur.append(s)
    flush()
    return paras

def sentences(path):
    return [s for p in paragraphs(path) for s in p]

def has_anchor(s):
    nonyears = YEARS.sub("", s)
    if re.search(NAMED, s) or re.search(r"\d", nonyears): return True
    toks = s.split()[1:]
    return any(re.match(r"^[A-Z][A-Za-z]{2,}", t) and t not in ("I", "I'm", "I've", "I'd") for t in toks)

def band(s):
    nonyears = YEARS.sub("", s)
    num = bool(re.search(r"\d", nonyears)); named = bool(re.search(NAMED, s))
    metric = bool(re.search(METRIC, nonyears, re.I)) and not s.startswith("Your")
    tech = bool(re.search(TECH, s))
    if (named and num) or metric: return "concrete"
    if named or num or tech: return "medium"
    return "generic"

def story_units(paras):
    """Count maximal runs of sentences covered by qualifying 3-sentence windows."""
    personal = example = covered = 0
    for ss in paras:
        in_p = [False] * len(ss); in_e = [False] * len(ss)
        for i in range(len(ss)):
            w = " ".join(ss[i:i + 3])
            if (re.search(r"\b(I|my|me)\b", w) and has_anchor(w) and (re.search(CAUSE, w, re.I) or re.search(CONTRAST, w, re.I) or re.search(FEELING, w, re.I)) and re.search(OUTCOME, w, re.I)):
                for j in range(i, min(i + 3, len(ss))): in_p[j] = True
            if re.search(EXAMPLE, w, re.I) and has_anchor(w):
                for j in range(i, min(i + 3, len(ss))): in_e[j] = True
        personal += sum(1 for i, v in enumerate(in_p) if v and (i == 0 or not in_p[i - 1]))
        example += sum(1 for i, v in enumerate(in_e) if v and (i == 0 or not in_e[i - 1]))
        covered += sum(in_p)
    return personal, example, covered

def analyze(paras):
    S = [s for p in paras for s in p]; n = max(len(S), 1)
    words = sum(len(s.split()) for s in S)
    b = {"concrete": 0, "medium": 0, "generic": 0}; carry = 0
    for p in paras:
        bands = [band(s) for s in p]
        for i, x in enumerate(bands):
            b[x] += 1
            carry += x == "generic" and not (i > 0 and bands[i - 1] != "generic")
    personal, example, covered = story_units(paras)
    return dict(sentences=len(S), words=words, wps=words / n,
        concrete=100 * b["concrete"] / n, medium=100 * b["medium"] / n, generic=100 * b["generic"] / n,
        generic_carry=100 * carry / n,
        first_I=100 * sum(bool(re.match(r"^I(\b|['’])", s)) for s in S) / n,
        skill=100 * sum(bool(OPENER.match(s)) for s in S) / n,
        flatter=100 * sum(bool(FLATTER.search(s)) for s in S) / n,
        personal_per_1000w=1000 * personal / max(words, 1), example_per_1000w=1000 * example / max(words, 1),
        in_story=100 * covered / n)

def windows(paras):
    """Return (kind, text) for each qualifying 3-sentence window, for hand-labelling with --show."""
    out = []
    for ss in paras:
        for i in range(len(ss)):
            w = " ".join(ss[i:i + 3])
            if (re.search(r"\b(I|my|me)\b", w) and has_anchor(w) and (re.search(CAUSE, w, re.I) or re.search(CONTRAST, w, re.I) or re.search(FEELING, w, re.I)) and re.search(OUTCOME, w, re.I)):
                out.append(("personal story", w))
            elif re.search(EXAMPLE, w, re.I) and has_anchor(w):
                out.append(("worked example", w))
    return out

if __name__ == "__main__":
    files = []                      # expand wildcards ourselves: PowerShell and cmd pass 'samples\\*.txt' through unchanged
    for a in sys.argv[1:]:
        if a.startswith("--"): continue
        hits = sorted(glob.glob(a)) or ([a] if os.path.isfile(a) else [])
        if not hits: print(f"no file matches: {a}  (run this from the folder that contains it)")
        files += hits
    if not files: sys.exit(1)
    cols = ["sentences", "words", "wps", "concrete", "medium", "generic", "generic_carry", "first_I", "skill", "flatter", "personal_per_1000w", "example_per_1000w", "in_story"]
    print(f"{'file':28s} " + " ".join(f"{c[:9]:>9s}" for c in cols))
    for f in files:
        a = analyze(paragraphs(f))
        print(f"{f[-28:]:28s} " + " ".join(f"{a[c]:9.1f}" for c in cols))
    if "--show" in sys.argv:        # prints your own text to your own screen only
        for f in files:
            print(f"\n== {f}")
            for kind, w in windows(paragraphs(f)):
                print(f"  [{kind}] {w[:240]}")

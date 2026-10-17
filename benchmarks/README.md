# Benchmark runs

Output of `scripts/benchmark.py`, one subfolder per run (`<timestamp>/`),
each with `report.md` (readable summary) and `results.json` (raw numbers).
Not checked in — these depend on the local model, the local database
snapshot, and whatever's in `logs/judging.log` at run time, so a committed
copy would just be stale noise. Run it yourself:

```
python scripts/benchmark.py                       # all three sections
python scripts/benchmark.py --agreement --timing   # read-only on the DB, no LM Studio needed
python scripts/benchmark.py --threads --repeats 3  # needs LM Studio up with the chat model loaded
```

See the script's own docstring for what each section measures and its limits.

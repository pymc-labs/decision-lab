import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Inspect a CSV or Parquet data file. Shows shape, columns, dtypes, missing values, duplicates, datetime range, and a sample of rows. Use this FIRST on any data file before writing analysis scripts so you know what columns exist and what they contain.",

  args: {
    path: tool.schema.string().describe("Path to data file (CSV or Parquet)"),
  },

  async execute({ path }) {
    const script = `
import sys, os
import pandas as pd

path = "${path}"
if not os.path.exists(path):
    print(f"ERROR: file not found: {path}")
    sys.exit(1)

ext = os.path.splitext(path)[1].lower()
if ext == ".parquet":
    df = pd.read_parquet(path)
elif ext in (".csv", ".tsv"):
    sep = "\\t" if ext == ".tsv" else ","
    df = pd.read_csv(path, sep=sep)
else:
    print(f"ERROR: unsupported extension {ext} (expected .csv, .tsv, or .parquet)")
    sys.exit(1)

print("=" * 70)
print(f"FILE: {path}")
print("=" * 70)
print(f"Shape: {df.shape[0]:,} rows x {df.shape[1]} cols")
print(f"Memory: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
print()

print("COLUMNS (name | dtype | n_missing | n_unique | sample):")
for col in df.columns:
    s = df[col]
    n_miss = int(s.isna().sum())
    n_uniq = int(s.nunique(dropna=True))
    sample = s.dropna().head(3).tolist()
    sample_str = ", ".join(repr(x) for x in sample)
    print(f"  {col!r:30s} | {str(s.dtype):15s} | miss={n_miss:>6} | uniq={n_uniq:>6} | e.g. [{sample_str}]")
print()

dup_rows = int(df.duplicated().sum())
print(f"Fully duplicated rows: {dup_rows}")

datetime_cols = []
for col in df.columns:
    if pd.api.types.is_datetime64_any_dtype(df[col]):
        datetime_cols.append(col)
        continue
    if df[col].dtype == object:
        try:
            parsed = pd.to_datetime(df[col].dropna().head(50), errors="raise")
            if parsed.notna().all():
                datetime_cols.append(col)
        except (ValueError, TypeError):
            pass

if datetime_cols:
    print()
    print("DATETIME-LIKE COLUMNS:")
    for col in datetime_cols:
        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
            mn, mx = parsed.min(), parsed.max()
            n_unique_dates = parsed.nunique()
            print(f"  {col!r}: {mn} -> {mx}  ({n_unique_dates:,} unique values)")
        except Exception as e:
            print(f"  {col!r}: could not parse ({e})")

print()
print("SAMPLE (first 5 rows):")
print(df.head(5).to_string())
`.trim()

    const result = await Bun.$`python -c ${script}`.nothrow()
    const stdout = result.stdout.toString()
    const stderr = result.stderr.toString()

    if (result.exitCode !== 0) {
      return `ERROR (exit code ${result.exitCode}):\n${stderr}\n\nStdout:\n${stdout}`
    }

    return stdout
  },
})

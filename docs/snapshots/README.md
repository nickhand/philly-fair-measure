# The snapshot program

The city overwrites `opa_properties_public` (every characteristic: livable
area, condition, exemptions) and `assessments` in place; whether past
assessment years get restated is unknowable without history. The program
also captured the legacy `real_estate_tax_delinquencies` table, now paused
and confirmed to have been labeled historical-only before our captures.
Once the city edits a record, the old value is gone. The weekly snapshot program is the only
mechanism by which "what did the city change?" stays answerable: enrollment
growth in the homestead exemption, characteristic corrections during appeal
season (see the current deadlines in
[`annual_report.json`](../../annual_report.json)), past-year restatements,
sheriff-sale flags.

## Source availability (verified 2026-11-02)

The scheduled job captures the tables in `SCHEDULED_CARTO_TABLES`
(`config.py`): the current-only `opa_properties_public` and `assessments`, and
`rtt_summary`, `permits` and `violations`.
Parcel-level `real_estate_tax_delinquencies` captures are **paused**: a live
`SELECT * FROM "real_estate_tax_delinquencies" LIMIT 0` against
<https://phl.carto.com/api/v2/sql> returns HTTP 403 with
`permission denied for table real_estate_tax_delinquencies`. The city has not
provided a reason in that response; do not assume the restriction is permanent.

The publication history provides context, not a confirmed cause for the 403:
OpenDataPhilly [replaced the parcel-level listing on 2024-07-10](https://github.com/opendataphilly/opendataphilly-jkan/pull/250/files).
The removed entry already said the data was not receiving updates and labeled
its downloads historical-only. Revenue's
[2024-09-23 announcement](https://www.phila.gov/2024-09-23-philly-releases-open-data-on-property-tax-delinquencies/)
describes the newer geographic aggregates and cites taxpayer privacy.
Neither source explains the September 2026 permission change. Successful
2026 downloads of the old table demonstrate accessibility, not current data.

The [2026-09-14 run](https://github.com/nickhand/philly-fair-measure/actions/runs/34806693492)
was the last successful scheduled capture. All seven weekly runs from
[2026-09-21](https://github.com/nickhand/philly-fair-measure/actions/runs/35561694241)
through [2026-11-02](https://github.com/nickhand/philly-fair-measure/actions/runs/41388461828)
failed; the first and last logs show this permission error. Although OPA and
assessments downloaded successfully, the failed fetch step prevented uploads
for those runs too. The November 2 log confirms that S3 still supplied
September 14 as the previous snapshot for all three tables. These missed
current-state captures cannot be reconstructed from a new fetch.

The current [OpenDataPhilly tax listing](https://opendataphilly.org/datasets/real-estate-tax-balances/)
links balances aggregated by ZIP, council district, and census tract. These
are not a parcel-level replacement. Preserve the existing raw delinquency
snapshots and their original timestamps; do not treat them as fresh or replace
missing updates with zero balances. The table is listed in
`PAUSED_CARTO_TABLES` (`config.py`), so a default `snapshot-all` skips it and
prints why, and a default `stage` builds the other tables without it.
`snapshot-all --tables real_estate_tax_delinquencies` still attempts the
source and exits 1 while access is denied.

A clean checkout therefore has no delinquency snapshot, and a rebuild there
leaves the delinquency features null. The published July 2026 models were
trained with the copy captured on 2026-07-03, whose records carry a June 2022
`year_month`.

Each scheduled run records this pause as a warning and in its job summary.
Before resuming, verify public API access and the parcel-level schema, then
remove the table from `PAUSED_CARTO_TABLES`, add it to `SCHEDULED_CARTO_TABLES`,
restore it to `TABLES` in the workflow and the `snapshot-current` recipe, and
remove the pause warning. A different source needs its own provenance.

## How it works

[`.github/workflows/snapshot.yml`](../../.github/workflows/snapshot.yml) runs
at 04:23 UTC every Monday (plus on demand via
`gh workflow run snapshot`):

1. pull the latest previous snapshot of each current-only table from S3,
2. fetch fresh copies of the scheduled tables via
   `fair-measure snapshot-all --tables $TABLES $EVENT_TABLES`,
3. upload the new parquet to S3 (`s3://<bucket>/raw/`, same layout as
   `data/raw/`),
4. run `fair-measure snapshot-diff` on the current-only tables and commit the
   summary to this directory as `YYYY-MM-DD.md`.

`snapshot-diff` covers only `opa_properties_public` and `assessments`. The
event tables (`rtt_summary`, `permits`, `violations`) have no diff spec, so the
job captures and uploads them without a summary. `fair-measure freshness`
checks only the scheduled tables, and `.github/ci/test_snapshot_tables.py`
fails when the workflow or `just snapshot-current` fetches a different set.

If one active source fails, completed snapshots from the other sources are
still uploaded, but the job remains failed and no diff summary is committed.
Directories ending in `.incomplete` are excluded from uploads and previous
snapshot selection. An empty S3 prefix is a valid first run; S3 access errors
still fail the job.

CARTO can also return HTTP 400 with `query_wait_timeout` when a query cannot
obtain a database connection (observed in the
[2026-11-02 verification run](https://github.com/nickhand/philly-fair-measure/actions/runs/41458154798)).
The downloader retries that exact error with its existing five-attempt
exponential backoff. Permission and SQL errors remain immediate failures.

The committed summary is the point of the program: a small, greppable record
of what changed, reviewed like any other diff. It also keeps the schedule
alive: GitHub disables cron workflows in public repos after 60 days without
repository activity, and the weekly bot commit resets that clock. Failure
emails go to the workflow author (GitHub's default for scheduled runs).

Raw parquet is never committed; it lives in S3. The July 2026 manifests put a
run at ~830 MB (~165 MB for the current-only tables), so a year adds ~43 GB,
about $1 a month at the S3 Standard list price.

## One-time AWS setup

The workflow authenticates with OIDC role assumption; no long-lived keys are
stored in GitHub. Run the setup below as a named profile, not the root
account: create an IAM Identity Center user (`aws configure sso --profile
philly-fair-measure`) or an IAM user with an access key (`aws configure
--profile philly-fair-measure`), then `export
AWS_PROFILE=philly-fair-measure` so these commands pick it up.
`aws sts get-caller-identity` confirms the profile and prints the
`<ACCOUNT_ID>` used below. The profile is only for this one-time setup and
optional local pulls; the workflow itself assumes the role keylessly.

Setup, once, with `<ACCOUNT_ID>` and a bucket name of your choosing:

1. **Bucket** (dedicated to this program):

   ```bash
   aws s3 mb s3://philly-fair-measure-snapshots
   ```

2. **GitHub OIDC identity provider** (skip if the account already has one):

   ```bash
   aws iam create-open-id-connect-provider \
     --url https://token.actions.githubusercontent.com \
     --client-id-list sts.amazonaws.com
   ```

3. **Role** the workflow assumes. Trust policy (`trust.json`), pinned to this
   repo's main branch:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": {
           "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
         },
         "Action": "sts:AssumeRoleWithWebIdentity",
         "Condition": {
           "StringEquals": {
             "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
             "token.actions.githubusercontent.com:sub": "repo:nickhand/philly-fair-measure:ref:refs/heads/main"
           }
         }
       }
     ]
   }
   ```

   Permissions policy (`policy.json`), scoped to the bucket:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": "s3:ListBucket",
         "Resource": "arn:aws:s3:::philly-fair-measure-snapshots"
       },
       {
         "Effect": "Allow",
         "Action": ["s3:GetObject", "s3:PutObject"],
         "Resource": "arn:aws:s3:::philly-fair-measure-snapshots/raw/*"
       }
     ]
   }
   ```

   ```bash
   aws iam create-role --role-name philly-fair-measure-snapshots \
     --assume-role-policy-document file://trust.json
   aws iam put-role-policy --role-name philly-fair-measure-snapshots \
     --policy-name s3-snapshots --policy-document file://policy.json
   ```

4. **Repo variables** (Settings -> Secrets and variables -> Actions ->
   Variables, or the CLI):

   ```bash
   gh variable set SNAPSHOT_BUCKET --body "philly-fair-measure-snapshots"
   gh variable set SNAPSHOT_AWS_REGION --body "us-east-1"
   gh variable set SNAPSHOT_ROLE_ARN \
     --body "arn:aws:iam::<ACCOUNT_ID>:role/philly-fair-measure-snapshots"
   ```

5. **Seed S3 with the local snapshots** so the first scheduled run has a
   previous month to diff against (the 2026-07-02 pull already contains the
   certified TY2027 roll):

   ```bash
   for ds in opa_properties_public assessments real_estate_tax_delinquencies; do
     aws s3 sync --size-only "data/raw/source=carto/dataset=$ds" \
       "s3://philly-fair-measure-snapshots/raw/source=carto/dataset=$ds"
   done
   ```

6. **Test it**: `gh workflow run snapshot`, then `gh run watch`. The
   run should end by pushing a `docs/snapshots/<date>.md` commit.

## Local use

The same commands work against the local lake, no AWS involved:

```bash
just snapshot-current      # fetch the two active tables + print the diff
uv run fair-measure snapshot-diff --datasets assessments   # one dataset
```

What gets compared per dataset (keys, watched columns, and the derived
notes) is defined in
[`ingest/diff.py`](../../src/philly_fair_measure/ingest/diff.py); comparisons
are null-safe, and duplicate keys in the raw feed are deduplicated keep-last.

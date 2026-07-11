# The monthly snapshot program

Three of our sources are current-state tables the city overwrites in place:
`opa_properties_public` (every characteristic: livable area, condition,
exemptions), `assessments` (whether past years get restated is unknowable
without history), and `real_estate_tax_delinquencies`. Once the city edits a
record, the old value is gone. The monthly snapshot program is the only
mechanism by which "what did the city change?" stays answerable: enrollment
growth in the homestead exemption, characteristic corrections during appeal
season (FLR by Sept 1, BRT by Oct 5), past-year restatements, sheriff-sale
flags.

## How it works

[`.github/workflows/snapshot.yml`](../../.github/workflows/snapshot.yml) runs
at 04:23 UTC on the 2nd of each month (plus on demand via
`gh workflow run monthly-snapshot`):

1. pull the latest previous snapshot per dataset from S3,
2. fetch fresh copies via `fair-measure snapshot-all --tables ...`,
3. upload the new parquet to S3 (`s3://<bucket>/raw/`, same layout as
   `data/raw/`),
4. run `fair-measure snapshot-diff` and commit the summary to this directory
   as `YYYY-MM-DD.md`.

The committed summary is the point of the program: a small, greppable record
of what changed, reviewed like any other diff. It also keeps the schedule
alive: GitHub disables cron workflows in public repos after 60 days without
repository activity, and the monthly bot commit resets that clock. Failure
emails go to the workflow author (GitHub's default for scheduled runs).

Raw parquet is never committed; it lives in S3 (~165 MB/month, ~$0.05/month
at standard rates).

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

6. **Test it**: `gh workflow run monthly-snapshot`, then `gh run watch`. The
   run should end by pushing a `docs/snapshots/<date>.md` commit.

## Local use

The same commands work against the local lake, no AWS involved:

```bash
just snapshot-current      # fetch the three tables + print the diff
uv run fair-measure snapshot-diff --datasets assessments   # one dataset
```

What gets compared per dataset (keys, watched columns, and the derived
notes) is defined in
[`ingest/diff.py`](../../src/philly_fair_measure/ingest/diff.py); comparisons
are null-safe, and duplicate keys in the raw feed are deduplicated keep-last.

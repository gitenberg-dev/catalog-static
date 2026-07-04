#!/usr/bin/env bash
# Pull the GITenberg Book table straight from the EB RDS — bypasses the flaky app.
# RUN THIS YOURSELF (Raymond): it (a) reads the DB password from EB config and
# (b) opens the RDS firewall to your IP — both things CC won't do. The SG rule is
# auto-revoked on exit (even on error/^C). The password stays in this shell only.
#
#   bash pull_gitenberg_db.sh
#
# Output: ./harvest/books_db.csv  (book_id,repo_name,title,language)
set -euo pipefail

REGION=us-east-1
APP=giten_site2
ENV=giten-site2-dev3
DBID=aaptgauwoocjjj
SG=sg-07fab1e8c02ccb16f
OUT="$(cd "$(dirname "$0")" && pwd)/harvest/books_db.csv"
mkdir -p "$(dirname "$OUT")"

# --- AWS creds (FEF-master). Uses the 1Password item you've used all week. ---
export AWS_ACCESS_KEY_ID="$(op read 'op://EbookFoundation/jfddsw7evpxpqh6vkoxm6af4mu/Access key')"
export AWS_SECRET_ACCESS_KEY="$(op read 'op://EbookFoundation/jfddsw7evpxpqh6vkoxm6af4mu/Secret access key')"
export AWS_DEFAULT_REGION="$REGION"

echo ">> resolving RDS endpoint + user…"
HOST=$(aws rds describe-db-instances --db-instance-identifier "$DBID" \
  --query 'DBInstances[0].Endpoint.Address' --output text)
USER=$(aws rds describe-db-instances --db-instance-identifier "$DBID" \
  --query 'DBInstances[0].MasterUsername' --output text)
DBNAME=$(aws rds describe-db-instances --db-instance-identifier "$DBID" \
  --query 'DBInstances[0].DBName' --output text)

# If you already set PGPASSWORD (e.g. after resetting the RDS master password), use it.
# Otherwise try EB config (usually masked -> will fail, then use the reset path).
if [ -z "${PGPASSWORD:-}" ]; then
  echo ">> PGPASSWORD not set; trying EB config…"
  export PGPASSWORD=$(aws elasticbeanstalk describe-configuration-settings \
    --application-name "$APP" --environment-name "$ENV" \
    --query "ConfigurationSettings[0].OptionSettings[?OptionName=='DBPassword'].Value | [0]" \
    --output text)
  if [ -z "${PGPASSWORD:-}" ] || [ "$PGPASSWORD" = "None" ] || [[ "$PGPASSWORD" =~ ^\*+$ ]]; then
    echo "!! DBPassword is masked/empty in EB config. Use the reset path (see CC)."
    exit 1
  fi
else
  echo ">> using PGPASSWORD from your environment."
fi

MYIP=$(curl -s https://checkip.amazonaws.com | tr -d '[:space:]')
echo ">> opening RDS firewall for ${MYIP}/32 (auto-revoked on exit)…"
aws ec2 authorize-security-group-ingress --group-id "$SG" \
  --protocol tcp --port 5432 --cidr "${MYIP}/32" >/dev/null

cleanup() {
  echo ">> revoking firewall rule for ${MYIP}/32…"
  aws ec2 revoke-security-group-ingress --group-id "$SG" \
    --protocol tcp --port 5432 --cidr "${MYIP}/32" >/dev/null 2>&1 || true
  unset PGPASSWORD
}
trap cleanup EXIT

echo ">> querying…"
PSQL=(/Applications/Postgres.app/Contents/Versions/latest/bin/psql
  "host=$HOST port=5432 dbname=$DBNAME user=$USER sslmode=require")

# exact total
"${PSQL[@]}" -tAc "SELECT COUNT(*) AS total_books FROM bookinfo_book;" | \
  awk '{print ">> EXACT book count: "$1}'

# full dump (client-side CSV to your laptop)
"${PSQL[@]}" -c "\copy (SELECT book_id, repo_name, title, language FROM bookinfo_book ORDER BY book_id) TO '$OUT' WITH (FORMAT csv, HEADER true)"

echo ">> wrote $OUT ($(wc -l < "$OUT") lines incl header)"
echo ">> done. Firewall rule will be revoked now. Tell CC the CSV is ready."

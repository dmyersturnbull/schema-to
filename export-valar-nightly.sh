#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

if (($# == 1)) && [[ "${1}" == "--help" ]]; then
  echo "Usage: ${0}"
  echo "Exports all the data in Valar as one gzipped sql file per table."
  exit 0
fi

if (($# > 0)); then
  (>&2 printf "Usage: %s\n" "$0")
  exit 1
fi

valar_user=admin
valar_password="${VALAR_PASSWORD:-}"
db_name=valar

if [[ -z "$valar_password" ]]; then
  (>&2 printf "Error: VALAR_PASSWORD is not set\n")
  exit 1
fi

interval=5000
declare -A big_tables=(
  ["sensor_data"]=1
  ["well_features"]=1
)

loc="/shire/backups/nightly"
prev_loc="/shire/backups/previous"
if [[ -e "$loc" ]]; then
  if [[ -e "$prev_loc" ]]; then
    rm -r -- "$prev_loc"
  fi
  mv -- "$loc" "$prev_loc"
fi
mkdir -p -- "$loc"

mariadb_args=(
  --skip-column-names
  --batch
  --skip-auto-rehash
  --user="$valar_user"
  --password="$valar_password"
  --database="$db_name"
)
mariadb_dump_args=(
  --max_allowed_packet=2147483648
  --skip-add-drop-table
  --skip-extended-insert
  --no-create-info
  --hex-blob
  --user="$valar_user"
  --password="$valar_password"
)

printf "Backing up to %s...\n" "$loc"
for t in $(mariadb "${mariadb_args[@]}" --execute='show tables'); do
  printf "Dumping %s..." "$t"
  if [[ -z "${big_tables[$t]:-}" ]]; then
    part_path="$loc/$t.sql.gz.part"
    final_path="$loc/$t.sql.gz"
    mariadb-dump "${mariadb_dump_args[@]}" -- "$db_name" "$t" | gzip > "$part_path"
    mv -- "$part_path" "$final_path"
  else
    n_rows=$(mariadb "${mariadb_args[@]}" --execute="select count(*) from $t")
    printf " partitioning %i rows..." "$n_rows"
    # Write create table structure only.
    part_path="$loc/${t}_0.sql.gz.part"
    final_path="$loc/${t}_0.sql.gz"
    mariadb-dump "${mariadb_dump_args[@]}" --no-data -- "$db_name" "$t" | gzip > "$part_path"
    mv -- "$part_path" "$final_path"
    # Write data in chunks using LIMIT/OFFSET to handle ID gaps.
    i=0
    remaining=$((n_rows))
    while ((remaining > 0)); do
      part_path="$loc/${t}_$((i+1)).sql.gz.part"
      final_path="$loc/${t}_$((i+1)).sql.gz"
      offset=$((i * interval))
      mariadb-dump "${mariadb_dump_args[@]}" --where="1=1 LIMIT $interval OFFSET $offset" -- "$db_name" "$t" | gzip > "$part_path"
      mv -- "$part_path" "$final_path"
      i=$((i+1))
      remaining=$((remaining - interval))
      printf " %i..." "$remaining"
    done
  fi
  printf " Done.\n"
done

printf "Backed up to %s\n" "$loc"

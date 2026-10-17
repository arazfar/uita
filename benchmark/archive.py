"""Save only demo benchmark cases, results and verification metadata to Railway."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from psycopg.types.json import Jsonb
from pipeline.uita_data.store import connect

ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = 'sfo-arrival-order-model-comparison-2026-08-03_07-v1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    comparison = json.loads((args.comparison/'comparison.json').read_text())
    files = {}
    if not comparison.get('provenance_verified'):
        raise ValueError('Generate and verify the comparison before archiving')
    for name in ['validation.jsonl', 'manifest.json', 'verification.json']:
        files['data/'+name] = (ROOT/'benchmark/data'/name).read_bytes()
    # The demo needs inputs, labels, predictions and aggregate scores. Raw API
    # responses, source code and unused development examples stay in the repo.
    files['comparison.json'] = (args.comparison/'comparison.json').read_bytes()
    case_ids = {json.loads(row)['case_id'] for row in files['data/validation.jsonl'].decode().splitlines()}
    if (len(case_ids) != comparison['validation_cases'] or
            case_ids != {r['case_id'] for r in comparison['per_case_results']}):
        raise ValueError('Comparison cases differ from the frozen validation data')
    if hashlib.sha256(files['data/validation.jsonl']).hexdigest() != comparison['validation_sha256']:
        raise ValueError('Validation checksum differs from the audited comparison')
    manifest = {'schema_version': 1, 'id': DATASET_ID, 'kind': 'historical_order_model_comparison',
                'task': comparison['task'], 'validation_cases': comparison['validation_cases'],
                'models': [m['model'] for m in comparison['models']],
                'held_out': comparison['held_out'], 'fine_tuning': 'deferred_by_user; no upload or job',
                'excluded': ['raw API logs', 'unused development/training payloads', 'final test payloads', 'source code'],
                'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                          for name, data in sorted(files.items())}}
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'id': DATASET_ID, 'artifacts': len(files)+1,
                          'bytes': sum(len(v) for v in files.values())}, indent=2))
        return
    files['manifest.json'] = (json.dumps(manifest, indent=2)+'\n').encode()
    with connect() as db:
        # Existing schema was created during the verified data delivery. No DDL or
        # unrelated tables change while archiving a comparison.
        prior = db.execute('SELECT manifest FROM uita_data.datasets WHERE id=%s', (DATASET_ID,)).fetchone()
        if prior and prior[0] != manifest:
            raise ValueError('A frozen comparison already exists with different contents; bump the dataset version')
        db.execute('INSERT INTO uita_data.datasets(id,manifest) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                   (DATASET_ID, Jsonb(manifest)))
        for name, data in files.items():
            db.execute('INSERT INTO uita_data.artifacts VALUES (%s,%s,%s,%b) ON CONFLICT DO NOTHING',
                       (DATASET_ID, name, hashlib.sha256(data).hexdigest(), data))
    with connect() as db:
        rows = db.execute("SELECT name,sha256,encode(sha256(payload),'hex') FROM uita_data.artifacts WHERE dataset_id=%s",
                          (DATASET_ID,)).fetchall()
    if len(rows) != len(files):
        raise ValueError('Archived artifact count mismatch')
    for name, expected, actual in rows:
        if actual != expected or actual != hashlib.sha256(files[name]).hexdigest():
            raise ValueError('Archived artifact checksum mismatch: '+name)
    report = {'passed': True, 'dataset_id': DATASET_ID, 'artifacts': len(files),
              'all_checksums_verified': True, 'contains_final_test_data': False,
              'validation_cases': len(case_ids), 'models': len(comparison['models']),
              'bytes': sum(len(data) for data in files.values()),
              'artifact_names': sorted(files)}
    (args.comparison/'railway-verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()

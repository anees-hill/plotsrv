import json
from pathlib import Path
import subprocess
import sys

from benchmarks.artifact_profile import KINDS


def test_real_renderer_campaign_republishes_and_reaps_receiver(tmp_path):
    output = tmp_path / 'run'
    process = subprocess.run([
        sys.executable, '-m', 'benchmarks.artifact_profile', '--output', str(output),
        '--clients', '2', '--cycles', '2', '--rounds', '1', '--settle', '0',
    ], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60)
    result = json.loads((output / 'run.json').read_text())
    assert process.returncode == 0, process.stdout + process.stderr
    assert result['status'] == 'completed'
    assert result['receiver']['exit_code_after_cleanup'] is not None
    for kind in KINDS:
        assert result['summary'][f'{kind}.cold.artifact']['latency_s']['count'] == 4
        assert result['summary'][f'{kind}.warm.artifact']['errors'] == 0
        assert result['summary'][f'{kind}.publish.publish']['latency_s']['count'] == 2
    records = json.loads((output / 'requests.json').read_text())
    for kind in KINDS:
        cold = [r['sha256'] for r in records if r['phase'] == f'{kind}.cold' and r['route'] == 'artifact']
        warm = [r['sha256'] for r in records if r['phase'] == f'{kind}.warm']
        assert cold == warm
        assert cold[0] != cold[-1]

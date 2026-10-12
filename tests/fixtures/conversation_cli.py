"""Deterministic model adapter used to verify real worker, HTTP and Git boundaries."""
import json
from pathlib import Path
import subprocess
import sys

context = json.loads(Path(sys.argv[1]).read_text().split('PROJECT CONTEXT\n', 1)[1])
if 'conversation_turn' in context:
    turn = context['conversation_turn']
    result = {'reply': 'Hello! I can talk with you.'}
    if 'fail once' in turn['message']['content'] and len(sys.argv) > 2:
        marker = Path(sys.argv[2])
        if not marker.exists():
            marker.write_text('failed once')
            raise SystemExit(1)
        result = {'reply': 'The retry recovered successfully.'}
    if turn['message']['content'] == 'Build feature.txt':
        result = {'reply': 'I can help with that work.'}
        if turn['can_create_tasks']:
            result['task_request'] = {'title': 'Build feature.txt', 'description': 'Commit and independently review feature.txt.'}
elif context['task']['kind'] == 'planning':
    result = {'summary': 'Planned the requested feature.', 'tasks': [{'title': 'Create feature.txt', 'description': 'Commit the feature.'}]}
elif 'Review the checked-out submission' in Path(sys.argv[1]).read_text():
    assert Path('feature.txt').read_text() == 'Conversation-driven feature\n'
    result = {'decision': 'approve', 'comment': 'Independent reviewer verified feature.txt.'}
else:
    Path('feature.txt').write_text('Conversation-driven feature\n')
    subprocess.run(['git', 'add', 'feature.txt'], check=True)
    subprocess.run(['git', 'commit', '-m', 'Add chat-requested feature'], check=True)
    result = {'summary': 'Feature committed and ready for independent review.'}
print('```agentverse\n' + json.dumps(result) + '\n```')

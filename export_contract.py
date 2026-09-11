import json
from pathlib import Path
import tempfile
from backend.app import create_app
with tempfile.TemporaryDirectory() as folder:
    schema=create_app(Path(folder)/'contract.db', interval=0).openapi()
    Path('docs/openapi.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

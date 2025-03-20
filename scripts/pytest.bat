pushd .
cd ..
echo on
set PYTHONPATH=%CD%
.venv\Scripts\python.exe -m pytest -n auto -v
popd

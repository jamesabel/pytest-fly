start "" "visualize.bat"
pushd .
cd ..
echo on
set PYTHONPATH=%CD%
del %LOCALAPPDATA%\abel\pytest-fly\pytest-fly.db
.venv\Scripts\python.exe -m pytest --fly -n auto -v
popd

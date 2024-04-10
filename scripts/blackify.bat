pushd .
cd ..
call .venv\Scripts\activate.bat
python -m black -l 192 src\pytest_fly tests
call deactivate
popd

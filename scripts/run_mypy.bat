pushd .
cd ..
call .venv\Scripts\activate.bat
mypy -m src
mypy -m tests
call deactivate
popd

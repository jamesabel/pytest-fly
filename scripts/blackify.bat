pushd .
cd ..
call venv\Scripts\activate.bat
python -m black -l 192 pytest_fly test_pytest_fly
call deactivate
popd

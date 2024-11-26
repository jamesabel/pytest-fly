pushd .
cd ..
set PYTHONPATH=%CD%
del /Q htmlcov
call .venv\Scripts\activate.bat
python -m pytest -p no:faulthandler -v --cov
coverage html
call deactivate
set PYTHONPATH=
popd

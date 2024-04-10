pushd .
cd ..
call .venv\Scripts\activate.bat
REM
REM E402 module level import not at top of file
REM F401 imported but unused
REM W503 line break before binary operator (black puts this in)
REM E203 whitespace before ':' (black puts this in and may be controversial)
REM E501 line too long
flake8 --ignore=E402,F401,W503,E203,E501 src\pytest_fly tests
call deactivate
popd

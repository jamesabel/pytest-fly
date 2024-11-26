REM make the venv
c:"\Program Files\Python312\python.exe" -m venv --clear .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\pip3 install -U -r requirements-dev.txt
REM install the pytest-fly package in editable mode
.venv\Scripts\pip3 install -U -e ..

pushd .
cd ..
rmdir /S /Q .venv
c:"\Program Files\Python313\python.exe" -m venv --clear .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\pip3 install -U setuptools
.venv\Scripts\pip3 install -U -r requirements-dev.txt
popd

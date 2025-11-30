pushd .
cd ..
rmdir /S /Q .venv
c:"\Program Files\Python314\python.exe" -m venv --clear .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\pip3 install -U setuptools
.venv\Scripts\pip3 install -U -r requirements-dev.txt
del requirements.txt
.venv\Scripts\python.exe -m piptools compile -q --strip-extras --output-file requirements.txt requirements-dev.txt
popd

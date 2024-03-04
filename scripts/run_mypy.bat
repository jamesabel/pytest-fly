pushd .
cd ..
call venv\Scripts\activate.bat 
mypy -m pressenter2exit
call deactivate
popd

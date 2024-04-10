pushd .
cd ..
rmdir /S /Q dist
call .venv\Scripts\activate.bat
hatch build
hatch publish
call deactivate
popd

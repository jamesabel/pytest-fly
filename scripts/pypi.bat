pushd .
cd ..
rmdir /S /Q pressenter2exit.egg-info
rmdir /S /Q build
rmdir /S /Q dist
copy /Y LICENSE LICENSE.txt
call venv\Scripts\activate.bat
python setup.py bdist_wheel
twine upload dist/*
rmdir /S /Q pressenter2exit.egg-info
rmdir /S /Q build
call deactivate
popd

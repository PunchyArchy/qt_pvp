from setuptools import setup, find_packages
from os.path import join, dirname

setup(
    name='qt_pvp',
    version='0.0.1',
    packages=find_packages(),
    author='punchyarchy',
    author_email='ksmdrmvscthny@gmail.com',
    long_description=open(join(dirname(__file__), 'readme.txt')).read(),
    install_requires=[
        'SQLAlchemy==1.4.29',
        'ws_one==1.12.41',
        'fastapi',
        'uvicorn',
        'requests'
    ],
)

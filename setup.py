from setuptools import setup, find_packages

setup(
    name='os-nova-servertester',
    author='Anton Aksola',
    author_email='aakso@iki.fi',
    license='Apache License, Version 2.0',
    version='0.0.1',
    packages=find_packages(),
    install_requires=[
        'python-novaclient'
    ],
    entry_points=dict(
        console_scripts=[
            'os_nova_servertester=os_nova_servertester.cmd.tester:main'
        ]
    ))

import versioneer
from setuptools import setup


extras_require = {
    'dev': [
        'coverage',
        'pytest',
        'pytest-cov',
    ],
}

extras_require['all'] = list({
    dep for deps in extras_require.values() for dep in deps})


install_requires = [
    'attrs',
    'awpa >= 0.16.1.0',
    'flake8 >= 3',
    'gather',
    'intervaltree',
    'six',
]


with open('README.rst') as infile:
    long_description = infile.read()


setup(
    name='codifer',
    description='building blocks for flake8 plugins',
    long_description=long_description,
    author='XXX',
    author_email='XXX',
    url='https://github.com/pyga/codifer',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development :: Quality Assurance',
    ],
    license='MIT',
    packages=[
        'codifer',
    ],
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    install_requires=install_requires,
    extras_require=extras_require,
    entry_points={
        'flake8.extension': [
            'twistedchecker = codifer:EbbLint',
        ],
    },
)

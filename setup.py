from setuptools import setup, find_packages

setup(
    name="doctor_digital",
    version="1.0.0",
    description="USB sanitization and file recovery toolkit for Windows",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[],  # stdlib only
    classifiers=[
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
    ],
)

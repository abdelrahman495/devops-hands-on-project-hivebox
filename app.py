"""
An initial version of the HiveBox app.
"""

# Using the Semantic Versioning v0.0.1
__version__ = "0.0.1"

def print_version():
    """
    This function prints the current app version and then exits.
    """
    print(f"App Version: {__version__}")
    exit(0)

if __name__ == "__main__":
    print_version()

import click


@click.group()
@click.version_option(version="0.1.0")
def main():
    """AA - Personal AI Assistant."""
    pass


if __name__ == "__main__":
    main()

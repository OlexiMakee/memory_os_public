import sys

def main():
    try:
        from memory_os.cli import main as cli_main
    except ImportError as e:
        print(f"Error importing memory_os.cli: {e}", file=sys.stderr)
        sys.exit(1)
    sys.exit(cli_main())

if __name__ == "__main__":
    main()

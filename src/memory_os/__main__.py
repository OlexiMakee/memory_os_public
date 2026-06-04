import sys

def main():
    try:
        from memory_os.cli import build_parser
    except ImportError as e:
        print(f"Error importing memory_os.cli: {e}", file=sys.stderr)
        sys.exit(1)
        
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "func"):
        sys.exit(args.func(args))
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()

import argparse
from datetime import timezone
from pathlib import Path

from memory_os import MemoryOSConfig

UTC = timezone.utc
def cmd_pipeline(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.pipeline import PipelineRunner
    runner = PipelineRunner(config)
    return runner.run(
        pipeline_name=args.name,
        custom_steps=getattr(args, "steps", None),
        notion_key=getattr(args, "notion_key", None),
        notion_db=getattr(args, "notion_db", None),
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        dry_run=args.dry_run,
    )

def cmd_linear_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.linear_sync import sync_roadmap_with_linear
    root_dir = Path(config.root_dir)
    success = sync_roadmap_with_linear(root_dir)
    return 0 if success else 1

def cmd_notion_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.notion_sync import sync_with_notion
    success = sync_with_notion(
        config=config,
        notion_api_key=args.api_key,
        notion_database_id=args.database_id,
        to_capsules=args.to_capsules
    )
    return 0 if success else 1

def cmd_gdrive_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.gdrive_sync import sync_with_gdrive
    success = sync_with_gdrive(
        config=config,
        access_token=args.token,
        folder_id=args.folder_id,
        to_capsules=args.to_capsules
    )
    return 0 if success else 1

import os
import sys
import typer

app = typer.Typer(help="Shift6 backend CLI")


def _prompts_dir() -> str:
    here = os.path.dirname(__file__)
    p = os.path.join(here, "system_prompts")
    return p


@app.command("prompts-list")
def prompts_list():
    """List available client prompt files (by slug)."""
    pdir = _prompts_dir()
    if not os.path.isdir(pdir):
        typer.echo("(none)")
        raise typer.Exit(0)
    slugs = []
    for name in os.listdir(pdir):
        if name.endswith(".md"):
            slugs.append(name[:-3])
    for s in sorted(slugs):
        typer.echo(s)


@app.command("prompts-show")
def prompts_show(slug: str):
    """Show prompt for a given client slug."""
    path = os.path.join(_prompts_dir(), f"{slug}.md")
    if not os.path.exists(path):
        typer.echo(f"missing: {path}")
        raise typer.Exit(1)
    with open(path, "r", encoding="utf-8") as f:
        typer.echo(f.read())


@app.command("prompts-set")
def prompts_set(slug: str, file: str = typer.Option(None, "--file", "-f", help="Path to .md file (optional). If omitted, read stdin.")):
    """Set/update prompt for a client slug from a file or stdin."""
    pdir = _prompts_dir()
    os.makedirs(pdir, exist_ok=True)
    path = os.path.join(pdir, f"{slug}.md")
    if file:
        with open(file, "r", encoding="utf-8") as fsrc:
            content = fsrc.read()
    else:
        content = sys.stdin.read()
    with open(path, "w", encoding="utf-8") as fdst:
        fdst.write(content)
    typer.echo(f"wrote {path}")


if __name__ == "__main__":
    app()


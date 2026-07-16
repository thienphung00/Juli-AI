export function isNavTabActive(activePath: string, href: string): boolean {
  if (href === "/") {
    return activePath === "/";
  }

  return activePath === href || activePath.startsWith(`${href}/`);
}

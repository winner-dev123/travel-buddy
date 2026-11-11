export interface HostingConfig {
  headers: { glob: string; headers: Record<string, string> }[];
  rewrites: { glob: string; path: string }[];
  cleanUrls: boolean;
  trailingSlashBehavior: string;
}

export function hostingConfig(apiOrigin: string): HostingConfig;

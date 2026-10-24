declare module "*.svg" {
  const content: string;
  export default content;
}

declare module "*.png" {
  const content: string;
  export default content;
}

declare module "*.jpg" {
  const content: string;
  export default content;
}

// Domain types (NewsArticle, Settings, SourceHealth, NewsFeedResponse, ...) live in
// ./types.ts and are imported explicitly. This file is asset-module shims only.

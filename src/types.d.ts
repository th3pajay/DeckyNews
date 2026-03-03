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

interface NewsArticle {
  title: string;
  link: string;
  published: string;
  source: string;
}

interface NewsFeedResponse {
  articles: NewsArticle[];
  total: number;
  page: number;
  totalPages: number;
}

interface SourceHealth {
  [key: string]: 'ok' | 'warning' | 'error';
}

interface Settings {
  refreshInterval: number;
  debugMode: boolean;
  sourcesEnabled: string[];
  analyticsOptIn: boolean;
}

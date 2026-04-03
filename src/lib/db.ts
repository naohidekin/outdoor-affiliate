import fs from "fs";
import path from "path";
import { Category, Product, Article, XPost } from "./types";

const DATA_DIR = path.join(process.cwd(), "data");

function readJson<T>(filename: string): T[] {
  const filePath = path.join(DATA_DIR, filename);
  if (!fs.existsSync(filePath)) return [];
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

function writeJson<T>(filename: string, data: T[]): void {
  const filePath = path.join(DATA_DIR, filename);
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf-8");
}

// Categories
export function getCategories(): Category[] {
  return readJson<Category>("categories.json").sort((a, b) => a.order - b.order);
}

export function getCategoryBySlug(slug: string): Category | undefined {
  return getCategories().find((c) => c.slug === slug);
}

export function getCategoryById(id: string): Category | undefined {
  return getCategories().find((c) => c.id === id);
}

export function saveCategory(category: Category): void {
  const categories = getCategories();
  const idx = categories.findIndex((c) => c.id === category.id);
  if (idx >= 0) categories[idx] = category;
  else categories.push(category);
  writeJson("categories.json", categories);
}

export function deleteCategory(id: string): void {
  const categories = getCategories().filter((c) => c.id !== id);
  writeJson("categories.json", categories);
}

// Products
export function getProducts(): Product[] {
  return readJson<Product>("products.json").sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
}

export function getProductById(id: string): Product | undefined {
  return getProducts().find((p) => p.id === id);
}

export function getProductsByCategory(categoryId: string): Product[] {
  return getProducts().filter((p) => p.categoryId === categoryId);
}

export function getProductsByIds(ids: string[]): Product[] {
  const products = getProducts();
  return ids.map((id) => products.find((p) => p.id === id)).filter(Boolean) as Product[];
}

export function saveProduct(product: Product): void {
  const products = getProducts();
  const idx = products.findIndex((p) => p.id === product.id);
  if (idx >= 0) products[idx] = product;
  else products.push(product);
  writeJson("products.json", products);
}

export function deleteProduct(id: string): void {
  const products = getProducts().filter((p) => p.id !== id);
  writeJson("products.json", products);
}

// Articles
export function getArticles(): Article[] {
  return readJson<Article>("articles.json").sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  );
}

export function getPublishedArticles(): Article[] {
  return getArticles().filter((a) => a.status === "published");
}

export function getArticleBySlug(slug: string): Article | undefined {
  return getArticles().find((a) => a.slug === slug);
}

export function getArticleById(id: string): Article | undefined {
  return getArticles().find((a) => a.id === id);
}

export function getArticlesByCategory(categoryId: string): Article[] {
  return getPublishedArticles().filter((a) => a.categoryId === categoryId);
}

export function saveArticle(article: Article): void {
  const articles = getArticles();
  const idx = articles.findIndex((a) => a.id === article.id);
  if (idx >= 0) articles[idx] = article;
  else articles.push(article);
  writeJson("articles.json", articles);
}

export function deleteArticle(id: string): void {
  const articles = getArticles().filter((a) => a.id !== id);
  writeJson("articles.json", articles);
}

// X Posts
export function getXPosts(): XPost[] {
  return readJson<XPost>("x-posts.json").sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
}

export function getXPostById(id: string): XPost | undefined {
  return getXPosts().find((p) => p.id === id);
}

export function saveXPost(post: XPost): void {
  const posts = getXPosts();
  const idx = posts.findIndex((p) => p.id === post.id);
  if (idx >= 0) posts[idx] = post;
  else posts.push(post);
  writeJson("x-posts.json", posts);
}

export function deleteXPost(id: string): void {
  const posts = getXPosts().filter((p) => p.id !== id);
  writeJson("x-posts.json", posts);
}

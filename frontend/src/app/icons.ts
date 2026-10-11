import {
  ArrowLeftRight,
  Coins,
  Crown,
  Hammer,
  Home,
  MessageCircle,
  Swords,
  TrendingDown,
  UserPlus,
  type LucideIcon,
} from "lucide-react";
import type { FeedKind } from "./feed";

/** One icon per kind of chronicle event (full page and sidebar). */
export const ICONS: Record<FeedKind, LucideIcon> = {
  build: Hammer,
  trade: ArrowLeftRight,
  people: UserPlus,
  talk: MessageCircle,
  price: Coins,
  job: Coins,
  home: Home,
  loss: TrendingDown,
  fight: Swords,
  decree: Crown,
};

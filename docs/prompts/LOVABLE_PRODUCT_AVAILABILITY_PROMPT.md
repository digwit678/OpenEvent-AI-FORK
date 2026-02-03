# Lovable Prompt: Product Availability Settings

## Context
Add a new "Product Availability" section to the existing `EventRequestsSetup.tsx` page. This section allows venue managers to control which products the AI recommends, which are available only on request, and which are completely unavailable.

## Reference Files
- **Design patterns:** `/src/pages/EventRequestsSetup.tsx` (follow the Card/Section structure)
- **Product list patterns:** `/src/pages/ProductsSetup.tsx` (category grouping, search, tabs)
- **UI components:** shadcn/ui (Card, Badge, Tabs, RadioGroup, Input, Collapsible)

---

## Feature Requirements

### Section: "Product Availability"
Add as a new Card section in EventRequestsSetup.tsx, after the existing "Notifications" section.

**Header:**
- Title: "Product Availability"
- Icon: Package (from lucide-react)
- Description: "Control which products AI recommends to clients"

### Three-Tier Availability System

**IMPORTANT:** Add a brief explanation at the top of the Product Availability section (above the search bar) showing what each status means. Use a similar card/pill layout as the Automation Mode section:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ● Recommended              ● On Request             ● Unavailable      │
│  AI actively suggests       Not suggested by AI,     Completely hidden  │
│  in offers & Q&A            only for special         from system        │
│                             client requests                             │
│                                                                         │
│  Best for: Standard         Best for: Seasonal or    Best for: Staff-   │
│  menu items                 special-order items      only or retired    │
└─────────────────────────────────────────────────────────────────────────┘
```

Each product can have one of three states (use RadioGroup with custom styled radio buttons):

| State | Label | User-Facing Description | Best For | Visual |
|-------|-------|-------------------------|----------|--------|
| `recommended` | "Recommended" | AI actively suggests this product in offers and answers client questions about it | Standard products, regular menu items | Green dot (default) |
| `on_request` | "On Request" | AI won't suggest it, but you can add it when a client specifically requests it | Seasonal items, special-order products, items needing pre-approval | Amber/yellow dot |
| `unavailable` | "Unavailable" | Completely hidden – cannot be added to any offer | Staff-only items, retired products, items under maintenance | Gray dot, faded row |

### UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ 📦 Product Availability                                         │
│ Control which products AI recommends to clients                 │
├─────────────────────────────────────────────────────────────────┤
│ [Search products...]                          [Expand All ▼]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ▼ Catering (14 recommended · 2 on request · 1 unavailable)     │
│ ┌─────────────────────────────────────────────────────────────┐│
│ │ Classic Apéro          ○ Recommended  ○ On Request  ○ Unavail││
│ │ CHF 18/person          ●              ○             ○        ││
│ ├─────────────────────────────────────────────────────────────┤│
│ │ Premium Apéro          ○ Recommended  ○ On Request  ○ Unavail││
│ │ CHF 28/person          ○              ●             ○        ││
│ ├─────────────────────────────────────────────────────────────┤│
│ │ Staff Lunch (faded)    ○ Recommended  ○ On Request  ○ Unavail││
│ │ CHF 12/person          ○              ○             ●        ││
│ └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│ ▶ Equipment (17 recommended · 0 on request · 0 unavailable)    │
│ ▶ Beverages (11 recommended · 0 on request ·si 0 unavailable)    │
│ ▶ Services (7 recommended · 0 on request · 0 unavailable)      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Interaction Patterns

1. **Category Collapsibles:**
   - Each category is a Collapsible section
   - Shows count summary: "X recommended · Y on request · Z unavailable"
   - Collapsed by default, expand on click
   - "Expand All" / "Collapse All" toggle button in header

2. **Product Row:**
   - Product name (bold) + price (muted, smaller)
   - Three radio buttons inline: Recommended | On Request | Unavailable
   - Unavailable products have faded/muted styling (opacity-50)
   - Auto-save on change (no save button needed)
   - **Tooltips on hover** for each radio option:
     - Recommended: "AI actively suggests this product and answers client questions"
     - On Request: "AI won't suggest this – only add when client specifically requests it"
     - Unavailable: "Completely hidden – cannot be added to any offer"

3. **Search:**
   - Filter products across all categories
   - Auto-expand matching categories when searching
   - Clear search button (X icon)

4. **Bulk Actions (per category):**
   - Small dropdown or buttons: "Set all to Recommended" | "Set all to On Request"
   - Only visible when category is expanded

### Visual Design

**Radio Button Styling (match existing automation mode pattern):**
```tsx
// Recommended = green accent
className={cn(
  "border-2 rounded-full w-4 h-4",
  status === 'recommended' ? "border-green-500 bg-green-500" : "border-muted-foreground/40"
)}

// On Request = amber accent
className={cn(
  "border-2 rounded-full w-4 h-4",
  status === 'on_request' ? "border-amber-500 bg-amber-500" : "border-muted-foreground/40"
)}

// Unavailable = gray
className={cn(
  "border-2 rounded-full w-4 h-4",
  status === 'unavailable' ? "border-gray-400 bg-gray-400" : "border-muted-foreground/40"
)}
```

**Category Header Badge Colors:**
- Recommended count: `bg-green-100 text-green-700`
- On Request count: `bg-amber-100 text-amber-700`
- Unavailable count: `bg-gray-100 text-gray-600`

### State Management

```typescript
interface ProductAvailability {
  product_id: string;
  status: 'recommended' | 'on_request' | 'unavailable';
}

// State shape
const [productAvailability, setProductAvailability] = useState<ProductAvailability[]>([]);

// Products come from existing useProducts() hook
// Availability status will be fetched/saved via API (placeholder for now)
```

### API Integration (placeholder)

For now, use local state. The actual API will be:
- `GET /api/config/product-availability` → Returns products with status
- `POST /api/config/product-availability` → Updates availability

Add TODO comments where API calls will go:
```typescript
// TODO: Fetch from GET /api/config/product-availability
// TODO: Save to POST /api/config/product-availability
```

### Responsive Design

- On mobile: Stack radio buttons vertically under product name
- On tablet+: Radio buttons inline with product name

---

## Do NOT Include

- Backend logic or database queries
- Actual API calls (use placeholders)
- Complex validation
- Undo/redo functionality

## Summary

Add a "Product Availability" Card section to EventRequestsSetup.tsx that:
1. Lists all products grouped by category (collapsible)
2. Each product has 3-state radio: Recommended / On Request / Unavailable
3. Search/filter functionality
4. Auto-save on change with toast feedback
5. Counts per category showing distribution
6. Follows existing design patterns (shadcn/ui, Tailwind)

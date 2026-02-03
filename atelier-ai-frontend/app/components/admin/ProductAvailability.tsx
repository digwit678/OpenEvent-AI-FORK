'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';

// Types
interface Product {
  product_id: string;
  name: string;
  category: string;
  unit: string | null;
  base_price: number;
  enabled: boolean;
}

interface ProductGroup {
  category: string;
  products: Product[];
  enabledCount: number;
}

export default function ProductAvailability() {
  const [products, setProducts] = useState<Product[]>([]);
  const [originalProducts, setOriginalProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Fetch products from API
  const fetchProducts = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_BASE || ''}/api/config/product-availability`);
      if (!res.ok) throw new Error('Failed to load products');
      const data = await res.json();
      setProducts(data.products);
      setOriginalProducts(JSON.parse(JSON.stringify(data.products)));
    } catch (err) {
      console.error(err);
      setNotification({ type: 'error', message: 'Could not load products.' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  // Clear notification after 3 seconds
  useEffect(() => {
    if (notification) {
      const timer = setTimeout(() => setNotification(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [notification]);

  // Check if there are unsaved changes
  const hasChanges = useMemo(() => {
    return products.some((p, i) => p.enabled !== originalProducts[i]?.enabled);
  }, [products, originalProducts]);

  // Count changes
  const changeCount = useMemo(() => {
    return products.filter((p, i) => p.enabled !== originalProducts[i]?.enabled).length;
  }, [products, originalProducts]);

  // Filter products by search query
  const filteredProducts = useMemo(() => {
    if (!searchQuery.trim()) return products;
    const query = searchQuery.toLowerCase();
    return products.filter(p =>
      p.name.toLowerCase().includes(query) ||
      p.category.toLowerCase().includes(query) ||
      p.product_id.toLowerCase().includes(query)
    );
  }, [products, searchQuery]);

  // Group products by category
  const productGroups = useMemo((): ProductGroup[] => {
    const groups: Record<string, Product[]> = {};
    for (const p of filteredProducts) {
      if (!groups[p.category]) groups[p.category] = [];
      groups[p.category].push(p);
    }
    return Object.entries(groups)
      .map(([category, prods]) => ({
        category,
        products: prods.sort((a, b) => a.name.localeCompare(b.name)),
        enabledCount: prods.filter(p => p.enabled).length,
      }))
      .sort((a, b) => a.category.localeCompare(b.category));
  }, [filteredProducts]);

  // Toggle a single product
  const toggleProduct = (productId: string) => {
    setProducts(prev => prev.map(p =>
      p.product_id === productId ? { ...p, enabled: !p.enabled } : p
    ));
  };

  // Enable/disable all products in a category
  const toggleCategory = (category: string, enable: boolean) => {
    setProducts(prev => prev.map(p =>
      p.category === category ? { ...p, enabled: enable } : p
    ));
  };

  // Enable/disable all products
  const toggleAll = (enable: boolean) => {
    setProducts(prev => prev.map(p => ({ ...p, enabled: enable })));
  };

  // Reset to original state
  const resetChanges = () => {
    setProducts(JSON.parse(JSON.stringify(originalProducts)));
  };

  // Save changes to API
  const saveChanges = async () => {
    try {
      setSaving(true);
      const disabledProducts = products.filter(p => !p.enabled).map(p => p.product_id);

      const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_BASE || ''}/api/config/product-availability`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ disabled_products: disabledProducts }),
      });

      if (!res.ok) throw new Error('Failed to save');

      const data = await res.json();
      setOriginalProducts(JSON.parse(JSON.stringify(products)));
      setNotification({
        type: 'success',
        message: `Saved! ${data.disabled_count} product(s) disabled.`
      });
    } catch (err) {
      console.error(err);
      setNotification({ type: 'error', message: 'Failed to save changes.' });
    } finally {
      setSaving(false);
    }
  };

  // Stats
  const totalCount = products.length;
  const enabledCount = products.filter(p => p.enabled).length;
  const disabledCount = totalCount - enabledCount;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-slate-400 animate-pulse">Loading products...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with stats */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <p className="text-slate-400 text-sm">
            Control which products are available in the workflow. Disabled products won't be suggested or selectable.
          </p>
          <div className="flex gap-4 mt-2 text-xs">
            <span className="text-emerald-400">{enabledCount} enabled</span>
            <span className="text-slate-500">|</span>
            <span className="text-amber-400">{disabledCount} disabled</span>
            <span className="text-slate-500">|</span>
            <span className="text-slate-400">{totalCount} total</span>
          </div>
        </div>

        {/* Bulk actions */}
        <div className="flex gap-2">
          <button
            onClick={() => toggleAll(true)}
            className="px-3 py-1.5 text-xs bg-emerald-600/20 text-emerald-400 rounded hover:bg-emerald-600/30 transition-colors"
          >
            Enable All
          </button>
          <button
            onClick={() => toggleAll(false)}
            className="px-3 py-1.5 text-xs bg-amber-600/20 text-amber-400 rounded hover:bg-amber-600/30 transition-colors"
          >
            Disable All
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <input
          type="text"
          placeholder="Search products..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full px-4 py-2 bg-slate-900/50 border border-slate-700/50 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-slate-600"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
          >
            ✕
          </button>
        )}
      </div>

      {/* Product groups */}
      <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
        {productGroups.map(group => (
          <div key={group.category} className="bg-slate-900/30 rounded-lg border border-slate-700/30">
            {/* Category header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/30">
              <div className="flex items-center gap-3">
                <span className="text-slate-200 font-medium">{group.category}</span>
                <span className="text-xs text-slate-500">
                  {group.enabledCount}/{group.products.length} enabled
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => toggleCategory(group.category, true)}
                  className="px-2 py-0.5 text-xs text-emerald-400 hover:bg-emerald-600/20 rounded transition-colors"
                >
                  All On
                </button>
                <button
                  onClick={() => toggleCategory(group.category, false)}
                  className="px-2 py-0.5 text-xs text-amber-400 hover:bg-amber-600/20 rounded transition-colors"
                >
                  All Off
                </button>
              </div>
            </div>

            {/* Products in category */}
            <div className="p-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {group.products.map(product => (
                <label
                  key={product.product_id}
                  className={`flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
                    product.enabled
                      ? 'bg-slate-800/30 hover:bg-slate-800/50'
                      : 'bg-amber-900/10 hover:bg-amber-900/20 opacity-60'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={product.enabled}
                    onChange={() => toggleProduct(product.product_id)}
                    className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-emerald-500 focus:ring-emerald-500 focus:ring-offset-0"
                  />
                  <div className="flex-1 min-w-0">
                    <div className={`text-sm truncate ${product.enabled ? 'text-slate-200' : 'text-slate-400'}`}>
                      {product.name}
                    </div>
                    {product.base_price > 0 && (
                      <div className="text-xs text-slate-500">
                        CHF {product.base_price.toFixed(2)} {product.unit === 'per_person' && '/ person'}
                      </div>
                    )}
                  </div>
                </label>
              ))}
            </div>
          </div>
        ))}

        {productGroups.length === 0 && (
          <div className="text-center py-8 text-slate-500">
            {searchQuery ? 'No products match your search.' : 'No products available.'}
          </div>
        )}
      </div>

      {/* Save bar */}
      {hasChanges && (
        <div className="sticky bottom-0 -mx-6 -mb-6 px-6 py-4 bg-slate-900/95 border-t border-slate-700/50 flex items-center justify-between">
          <span className="text-sm text-amber-400">
            {changeCount} unsaved change{changeCount !== 1 ? 's' : ''}
          </span>
          <div className="flex gap-3">
            <button
              onClick={resetChanges}
              className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
            >
              Reset
            </button>
            <button
              onClick={saveChanges}
              disabled={saving}
              className="px-4 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      )}

      {/* Notification */}
      {notification && (
        <div className={`fixed bottom-6 right-6 px-4 py-3 rounded-lg shadow-lg ${
          notification.type === 'success' ? 'bg-emerald-600' : 'bg-red-600'
        } text-white text-sm`}>
          {notification.message}
        </div>
      )}
    </div>
  );
}

'use client';

import { Suspense } from 'react';
import { DebugLayout } from '../../components/debug/DebugHeader';
import ProductAvailability from '../../components/admin/ProductAvailability';

function ProductIcon() {
  return (
    <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
    </svg>
  );
}

function ProductsPageContent() {
  return (
    <DebugLayout
      title="Product Availability"
      icon={<ProductIcon />}
    >
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-6">
        <ProductAvailability />
      </div>
    </DebugLayout>
  );
}

export default function ProductsPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-slate-400 animate-pulse">Loading products...</div>
      </div>
    }>
      <ProductsPageContent />
    </Suspense>
  );
}

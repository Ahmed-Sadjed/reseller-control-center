import { useState, useEffect, useCallback } from 'react';
import Layout from '../components/Layout';
import BalanceHeader from '../components/BalanceHeader';
import ProductCard from '../components/ProductCard';
import api from '../lib/axios';
import { useBalance } from '../hooks/useBalance';

export default function CatalogPage() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const { balance, refresh } = useBalance();

  const fetchProducts = useCallback(async () => {
    try {
      const { data } = await api.get('/products/');
      setProducts(data.results || data);
    } catch {
      setError('Failed to load products');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  const handleError = (msg) => {
    setError(msg);
    setTimeout(() => setError(''), 5000);
  };

  return (
    <Layout>
      <div className="space-y-6">
        <BalanceHeader balance={balance} />
        {error && (
          <div className="bg-red-50 text-red-700 px-4 py-3 rounded text-sm">
            {error}
          </div>
        )}
        <h1 className="text-2xl font-bold text-gray-900">Catalog</h1>
        {loading ? (
          <div className="text-center py-12 text-gray-500">Loading products...</div>
        ) : products.length === 0 ? (
          <div className="text-center py-12 text-gray-500">No products available.</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {products.map((product) => (
              <ProductCard
                key={product.id}
                product={product}
                onError={handleError}
              />
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}

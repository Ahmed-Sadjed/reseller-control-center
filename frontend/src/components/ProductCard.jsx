import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../lib/axios';

// Inline UUID v4 generator (avoids needing the uuid package)
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export default function ProductCard({ product, onError }) {
  const [quantity, setQuantity] = useState(1);
  const [buying, setBuying] = useState(false);
  const navigate = useNavigate();

  const handleBuy = async () => {
    setBuying(true);
    const idempotencyKey = generateUUID();
    try {
      const { data } = await api.post('/purchase/', {
        product_id: product.id,
        quantity,
      }, {
        headers: { 'Idempotency-Key': idempotencyKey },
      });
      if (data.status === 'PENDING') {
        navigate(`/processing/${data.order_id}`);
      } else {
        navigate(`/receipt/${data.order_id}`);
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Purchase failed';
      if (onError) onError(msg);
    } finally {
      setBuying(false);
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200 hover:shadow-lg transition-shadow">
      <h3 className="text-lg font-semibold text-gray-900">{product.name}</h3>
      <p className="text-sm text-gray-500 mt-1">{product.description}</p>
      <div className="mt-3 flex items-center justify-between">
        <span className="text-2xl font-bold text-indigo-600">
          {product.price_in_credits}
        </span>
        <span className="text-sm text-gray-500">
          {product.duration_months}mo
        </span>
      </div>
      <div className="mt-4 flex items-center space-x-3">
        <label className="text-sm text-gray-600">Qty:</label>
        <input
          type="number"
          min={1}
          max={50}
          value={quantity}
          onChange={(e) => setQuantity(Math.min(50, Math.max(1, parseInt(e.target.value) || 1)))}
          className="w-20 px-2 py-1 border border-gray-300 rounded text-center"
        />
        <button
          onClick={handleBuy}
          disabled={buying}
          className="flex-1 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {buying ? 'Buying...' : 'Buy Now'}
        </button>
      </div>
    </div>
  );
}

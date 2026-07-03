import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../lib/axios';

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

  const variants = product.variants || [];
  const [selectedVariant, setSelectedVariant] = useState(variants[0] || null);
  const showVariants = variants.length > 1;

  const handleBuy = async () => {
    if (!selectedVariant) return;
    setBuying(true);
    const idempotencyKey = generateUUID();
    try {
      const { data } = await api.post('/purchase/', {
        variant_id: selectedVariant.id,
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
          {selectedVariant ? `${selectedVariant.price_in_credits}` : 'N/A'}
        </span>
        <span className="text-sm text-gray-500">credits</span>
      </div>
      {showVariants && variants.length > 0 && (
        <div className="mt-4">
          <label className="text-sm text-gray-600 block mb-1">Duration:</label>
          <div className="flex gap-2">
            {variants.map((v) => (
              <button
                key={v.id}
                onClick={() => setSelectedVariant(v)}
                className={`px-3 py-1.5 text-sm font-medium rounded transition-colors ${
                  selectedVariant?.id === v.id
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {v.display_name}
              </button>
            ))}
          </div>
        </div>
      )}
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
          disabled={buying || !selectedVariant}
          className="flex-1 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {buying ? 'Buying...' : 'Buy Now'}
        </button>
      </div>
    </div>
  );
}

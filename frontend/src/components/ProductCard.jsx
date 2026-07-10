import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../lib/axios';

const MAC_REGEX = /^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$/;

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function getDurationVariant(variants, label) {
  if (label === 'forever') return variants.find((v) => v.display_name === 'Lifetime') || variants[variants.length - 1];
  return variants.find((v) => v.display_name !== 'Lifetime') || variants[0];
}

export default function ProductCard({ product, onError }) {
  const [quantity, setQuantity] = useState(1);
  const [buying, setBuying] = useState(false);
  const navigate = useNavigate();

  const variants = product.variants || [];
  const [selectedVariant, setSelectedVariant] = useState(variants[0] || null);

  const isHotPlayer = product.provider_key === 'hotplayer';

  // MAC modal state
  const [showMacModal, setShowMacModal] = useState(false);
  const [macInput, setMacInput] = useState('');
  const [noteInput, setNoteInput] = useState('');
  const [modalDuration, setModalDuration] = useState('year');
  const [modalError, setModalError] = useState('');
  const [activating, setActivating] = useState(false);

  const handleBuy = () => {
    if (!selectedVariant) return;
    if (isHotPlayer) {
      const initialDuration = selectedVariant.display_name === 'Lifetime' ? 'forever' : 'year';
      setMacInput('');
      setNoteInput('');
      setModalDuration(initialDuration);
      setModalError('');
      setShowMacModal(true);
      return;
    }
    submitPurchase(selectedVariant.id, quantity);
  };

  const submitPurchase = async (variantId, qty, mac, note) => {
    setBuying(true);
    const idempotencyKey = generateUUID();
    try {
      const body = { variant_id: variantId, quantity: qty };
      if (mac) body.mac = mac;
      if (note) body.note = note;
      const { data } = await api.post('/purchase/', body, {
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
      throw err;
    } finally {
      setBuying(false);
    }
  };

  const handleActivate = async () => {
    const trimmedMac = macInput.trim();
    if (!trimmedMac) {
      setModalError('MAC address is required.');
      return;
    }
    if (!MAC_REGEX.test(trimmedMac)) {
      setModalError('Invalid MAC address. Use format XX:XX:XX:XX:XX:XX');
      return;
    }
    setModalError('');
    setActivating(true);
    const variant = getDurationVariant(variants, modalDuration);
    if (!variant) {
      setModalError('No valid variant selected.');
      setActivating(false);
      return;
    }
    try {
      await submitPurchase(variant.id, 1, trimmedMac.toUpperCase(), noteInput.trim());
      setShowMacModal(false);
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Activation failed';
      setModalError(msg);
    } finally {
      setActivating(false);
    }
  };

  const handleCancel = () => {
    setShowMacModal(false);
    setMacInput('');
    setNoteInput('');
    setModalError('');
  };

  return (
    <div className="bg-white rounded-lg shadow-md border border-gray-200 hover:shadow-lg transition-shadow overflow-hidden">
      {product.thumbnail_url && (
        <div className="aspect-video bg-gray-100 overflow-hidden">
          <img
            src={product.thumbnail_url}
            alt={product.name}
            className="w-full h-full object-cover"
          />
        </div>
      )}
      <div className="p-6">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-lg font-semibold text-gray-900">{product.name}</h3>
          {product.provider_name && (
            <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded whitespace-nowrap">
              {product.provider_name}
            </span>
          )}
        </div>
        {product.description && (
          <p className="text-sm text-gray-500 mt-1 line-clamp-2">{product.description}</p>
        )}
        <div className="mt-3 flex items-center justify-between">
          <span className="text-2xl font-bold text-indigo-600">
            {selectedVariant ? `${selectedVariant.price_in_credits}` : 'N/A'}
          </span>
          <span className="text-sm text-gray-500">credits</span>
        </div>
        {variants.length > 0 && (
          <div className="mt-4">
            <label className="text-sm text-gray-600 block mb-1">Duration:</label>
            <div className="flex gap-2">
              {variants.length === 1 ? (
                <span className="px-3 py-1.5 text-sm font-medium rounded bg-gray-100 text-gray-500 cursor-default">
                  {variants[0].display_name || 'Lifetime'}
                </span>
              ) : (
                variants.map((v) => (
                  <button
                    key={v.id}
                    onClick={() => setSelectedVariant(v)}
                    className={`px-3 py-1.5 text-sm font-medium rounded transition-colors ${
                      selectedVariant?.id === v.id
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    {v.display_name || 'Lifetime'}
                  </button>
                ))
              )}
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

      {showMacModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={handleCancel}>
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-xl font-semibold text-gray-900 mb-4">Activate Device</h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  MAC Address <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={macInput}
                  onChange={(e) => setMacInput(e.target.value)}
                  placeholder="00:1A:79:AB:CD:EF"
                  maxLength={17}
                  className="w-full px-3 py-2 border border-gray-300 rounded font-mono text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Subscription</label>
                <div className="flex gap-2">
                  <button
                    onClick={() => setModalDuration('year')}
                    className={`flex-1 px-3 py-2 text-sm font-medium rounded transition-colors ${
                      modalDuration === 'year'
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    1 YEAR (1 CREDIT)
                  </button>
                  <button
                    onClick={() => setModalDuration('forever')}
                    className={`flex-1 px-3 py-2 text-sm font-medium rounded transition-colors ${
                      modalDuration === 'forever'
                        ? 'bg-indigo-600 text-white shadow-sm'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    FOREVER (2.5 CREDITS)
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Note <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <textarea
                  value={noteInput}
                  onChange={(e) => setNoteInput(e.target.value)}
                  placeholder="Client: John's Firestick"
                  rows={2}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
            </div>

            {modalError && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                {modalError}
              </div>
            )}

            <div className="mt-6 flex gap-3">
              <button
                onClick={handleActivate}
                disabled={activating}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {activating ? 'Activating...' : 'Activate'}
              </button>
              <button
                onClick={handleCancel}
                disabled={activating}
                className="flex-1 px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

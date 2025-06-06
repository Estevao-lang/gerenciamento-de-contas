// Script para manipulação de datas e melhorias de UX
document.addEventListener('DOMContentLoaded', function() {
    // Definir data mínima para o campo de data (hoje)
    const hoje = new Date().toISOString().split('T')[0];
    document.getElementById('data_vencimento').min = hoje;
    
    // Atualizar contadores em tempo real
    const valorInput = document.getElementById('valor');
    if (valorInput) {
        valorInput.addEventListener('input', function(e) {
            // Formatação em tempo real para moeda
            let value = e.target.value.replace(/\D/g, '');
            value = (value / 100).toFixed(2) + '';
            value = value.replace('.', ',');
            value = value.replace(/(\d)(\d{3})(\d{3}),/g, '$1.$2.$3,');
            value = value.replace(/(\d)(\d{3}),/g, '$1.$2,');
            e.target.value = value;
        });
    }
    
    // Adicionar máscara de moeda para campos de valor
    const valorFields = document.querySelectorAll('input[type="number"][step="0.01"]');
    valorFields.forEach(field => {
        field.addEventListener('blur', function() {
            this.value = parseFloat(this.value).toFixed(2);
        });
    });
});
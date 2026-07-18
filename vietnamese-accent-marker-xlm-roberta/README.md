---
license: apache-2.0
language:
- vi
pipeline_tag: token-classification
tags:
- vietnamese
- accents inserter
- diacritics
metrics:
- accuracy
---

# A Transformer model for inserting Vietnamese accent marks

This model inserts accent marks (diacritics) for Vietnamese texts that don't have them (or texts with some words accented and some not). 

Example input: Nhin nhung mua thu di  
Target output: Nhìn những mùa thu đi


## Model training
This problem was modelled as a token classification problem. For each input token, the goal is to asssign a "tag" that will transform it
to the accented token.  

This model is finetuned from the XLM-Roberta Large. For more details on the training process, please refer to this 
<a href="https://peterhung.org/tech/insert-vietnamese-accent-transformer-model/" target="_blank">blog post</a>.


## How to use this model
There are just a few steps: 
- Step 1: Load the model as a token classification model (`AutoModelForTokenClassification`).
- Step 2: Run the input through the model to obtain the tag index for each input token.
- Step 3: Use the tags' index to retreive the actual tags in the file `selected_tags_names.txt`. Then,
  apply the conversion indicated by the tag to each token to obtain accented tokens.

### Step 1: Load model
Note: Install *transformers*, *torch*, *numpy* packages first. 

```python
from transformers import AutoTokenizer, AutoModelForTokenClassification
import torch
import numpy as np

def load_trained_transformer_model():
    model_path = "peterhung/vietnamese-accent-marker-xlm-roberta"
    tokenizer = AutoTokenizer.from_pretrained(model_path, add_prefix_space=True)
    model = AutoModelForTokenClassification.from_pretrained(model_path)
    return model, tokenizer

model, tokenizer = load_trained_transformer_model() 
```

### Step 2: Run input text through the model 

```python
# only needed if it's run on GPU
device = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
model.to(device)

# set to eval mode
model.eval()

def insert_accents(text, model, tokenizer):
    our_tokens = text.strip().split()

    # the tokenizer may further split our tokens
    inputs = tokenizer(our_tokens,
                        is_split_into_words=True,
                        truncation=True,
                        padding=True,
                        return_tensors="pt"
                        )
    input_ids = inputs['input_ids']
    tokens = tokenizer.convert_ids_to_tokens(input_ids[0])
    tokens = tokens[1:-1]

    with torch.no_grad():
        inputs.to(device)
        outputs = model(**inputs)

    predictions = outputs["logits"].cpu().numpy()
    predictions = np.argmax(predictions, axis=2)

    # exclude output at index 0 and the last index, which correspond to '<s>' and '</s>'
    predictions = predictions[0][1:-1]

    assert len(tokens) == len(predictions)

    return tokens, predictions 


text = "Nhin nhung mua thu di, em nghe sau len trong nang."
tokens, predictions = insert_accents(text, model, tokenizer)
```

### Step3: Obtain the accented words 

3.1 Download the tags set file (`selected_tags_names.txt`) from this repo. 
Suppose that it's put int the current dir, we can then load it: 
```python
def _load_tags_set(fpath):
    labels = []
    with open(fpath, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                labels.append(line)

    return labels
    
label_list = _load_tags_set("./selected_tags_names.txt")
assert len(label_list) == 528, f"Expect {len(label_list)} tags"
```

3.2 Print out `tokens` and `predictions` obtained above to see what we're having here
```python
print(tokens)
print(list(f"{pred} ({label_list[pred]})" for pred in predictions))
```

Obtained 
```python
['▁Nhi', 'n', '▁nhu', 'ng', '▁mua', '▁thu', '▁di', ',', '▁em', '▁nghe', '▁sau', '▁len', '▁trong', '▁nang', '.']
['217 (i-ì)', '217 (i-ì)', '388 (u-ữ)', '388 (u-ữ)', '407 (ua-ùa)', '378 (u-u)', '120 (di-đi)', '0 (-)', '185 (e-e)', '185 (e-e)', '41 (au-âu)', '188 (e-ê)', '302 (o-o)', '14 (a-ắ)', '0 (-)']
```

We can see here that our original words have been further split into smaller tokens by the model. But we know the first token of each word 
starts with the special char "▁".  

Here, we'd need to merge these tokens (and similarly, the corresponding tags) into our original Vietnamese words. 
Then, for each word, we'd apply the first tag (if it's associated with more than 1 tags) that change the word.  

This can be done as follows: 

```python
TOKENIZER_WORD_PREFIX = "▁"
def merge_tokens_and_preds(tokens, predictions): 
    merged_tokens_preds = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        label_indexes = set([predictions[i]])
        if tok.startswith(TOKENIZER_WORD_PREFIX): # start a new word
            tok_no_prefix = tok[len(TOKENIZER_WORD_PREFIX):]
            cur_word_toks = [tok_no_prefix]
            # check if subsequent toks are part of this word
            j = i + 1
            while j < len(tokens):
                if not tokens[j].startswith(TOKENIZER_WORD_PREFIX):
                    cur_word_toks.append(tokens[j])
                    label_indexes.add(predictions[j])
                    j += 1
                else:
                    break
            cur_word = ''.join(cur_word_toks)
            merged_tokens_preds.append((cur_word, label_indexes))
            i = j
        else:
            merged_tokens_preds.append((tok, label_indexes))
            i += 1

    return merged_tokens_preds


merged_tokens_preds = merge_tokens_and_preds(tokens, predictions)
print(merged_tokens_preds)
```

Obtained: 
```python
[('Nhin', {217}), ('nhung', {388}), ('mua', {407}), ('thu', {378}), ('di,', {120, 0}), ('em', {185}), ('nghe', {185}), ('sau', {41}), ('len', {188}), ('trong', {302}), ('nang.', {0, 14})]
```

For each word, we now have a set of tag indexes to apply to it. 
For ex, for the first word "Nhin" above, we'd apply the tag at index `217` in our tags set. 

The following is our final part: 

```python
def get_accented_words(merged_tokens_preds, label_list):
    accented_words = []
    for word_raw, label_indexes in merged_tokens_preds:
        # use the first label that changes word_raw
        for label_index in label_indexes:
            tag_name = label_list[int(label_index)]
            raw, vowel = tag_name.split("-")
            if raw and raw in word_raw:
                word_accented = word_raw.replace(raw, vowel)
                break
        else:
            word_accented = word_raw

        accented_words.append(word_accented)

    return accented_words


accented_words = get_accented_words(merged_tokens_preds, label_list)
print(accented_words)
```

Obtained: 
```python
['Nhìn', 'những', 'mùa', 'thu', 'đi,', 'em', 'nghe', 'sâu', 'lên', 'trong', 'nắng.']
```

In this example, the model made 1 mistake with the word "sầu" (but predicted "sâu"). 



## Limitations 
- This model will accept a maximum of 512 tokens, which is a limitation inherited from the base pretrained XLM-Roberta model.
- It has a higher accuracy (97%) than <a href="https://vietnameseaccent.com/" target="_blank">the HMM version</a> (91%), 
but at the expense of a probably longer running time. 
More info can be found <a href="https://peterhung.org/tech/insert-vietnamese-accent-transformer-model/#vs-hmm" target="_blank">here</a>.



## Live Demo
- You can use the inference API on the right side of this page (provided by HF automatically) 
to see the tags (indexes) assigned to each word.

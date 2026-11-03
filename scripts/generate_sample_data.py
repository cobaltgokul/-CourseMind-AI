"""
generate_sample_data.py
------------------------
One-off utility: generates realistic-looking sample course PDFs (5+ per
course, across 2 courses) so the multi-course demo has real material to
index and query, without needing any external downloads.

Run once from the project root:
    python3 scripts/generate_sample_data.py

Output goes straight into backend/data/faculty_uploads/<course_id>/, i.e.
exactly where faculty_watch.py expects to find (and auto-index) new files.
"""

from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

BASE = Path(__file__).parent.parent / "backend" / "data" / "faculty_uploads"

styles = getSampleStyleSheet()
title_style = ParagraphStyle("TitleX", parent=styles["Title"], fontSize=16, spaceAfter=14)
h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12.5, spaceBefore=12, spaceAfter=6)
body = ParagraphStyle("BodyX", parent=styles["BodyText"], fontSize=10.3, leading=15, spaceAfter=8)


def make_pdf(course_id: str, filename: str, title: str, sections: list):
    """sections: list of (heading, paragraph_text)"""
    out_dir = BASE / course_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename

    doc = SimpleDocTemplate(str(path), pagesize=LETTER,
                             topMargin=0.9 * inch, bottomMargin=0.9 * inch,
                             leftMargin=0.9 * inch, rightMargin=0.9 * inch)
    story = [Paragraph(title, title_style), Spacer(1, 6)]
    for heading, text in sections:
        story.append(Paragraph(heading, h2))
        story.append(Paragraph(text, body))
    doc.build(story)
    print(f"Created {path}")


# ============================================================ ISWE411L ===
# Deep Learning

make_pdf(
    "ISWE411L", "M1-neural-network-fundamentals.pdf",
    "Module 1: Neural Network Fundamentals",
    [
        ("What is a Neural Network",
         "A neural network is a computational model inspired by the structure of the human "
         "brain. It consists of layers of interconnected nodes, or neurons. Each connection "
         "has an associated weight, and each neuron applies an activation function to the "
         "weighted sum of its inputs."),
        ("Layers",
         "The three main types of layers are the input layer, one or more hidden layers, and "
         "the output layer. Deeper networks (more hidden layers) can represent more complex "
         "functions, which is where the term 'deep learning' comes from."),
        ("Training via Backpropagation",
         "Training a neural network involves adjusting the weights using an algorithm called "
         "backpropagation, combined with an optimization method such as stochastic gradient "
         "descent (SGD). Backpropagation computes the gradient of the loss function with "
         "respect to each weight by applying the chain rule layer by layer, from the output "
         "back to the input."),
        ("Activation Functions",
         "Common activation functions include ReLU (Rectified Linear Unit), sigmoid, and tanh. "
         "ReLU is widely used in modern deep networks because it helps avoid the vanishing "
         "gradient problem and is computationally cheap. Sigmoid squashes values between 0 and "
         "1 and is common in binary classification output layers."),
        ("Midterm Note",
         "The course's midterm exam will cover neural network fundamentals, including forward "
         "propagation, backpropagation, and activation functions. It is scheduled for the 6th "
         "week of the semester."),
    ]
)

make_pdf(
    "ISWE411L", "M2-convolutional-neural-networks.pdf",
    "Module 2: Convolutional Neural Networks (CNNs)",
    [
        ("Motivation",
         "Convolutional Neural Networks are designed primarily for grid-like data such as "
         "images. Unlike fully-connected layers, convolutional layers exploit spatial "
         "structure, dramatically reducing the number of parameters compared to a dense "
         "network processing raw pixels."),
        ("Convolutional Layers",
         "A convolutional layer applies a set of learnable filters (kernels) across the input, "
         "producing feature maps that highlight patterns such as edges, textures, and shapes. "
         "Early layers tend to detect simple features; deeper layers combine them into more "
         "abstract representations."),
        ("Pooling",
         "Pooling layers (commonly max pooling) downsample feature maps, reducing spatial "
         "dimensions and computation while providing some translation invariance."),
        ("Classic Architectures",
         "Well-known CNN architectures include LeNet, AlexNet, VGG, and ResNet. ResNet "
         "introduced skip connections (residual connections) that allow gradients to flow "
         "through very deep networks without vanishing, enabling networks with over 100 "
         "layers to train effectively."),
        ("Applications",
         "CNNs are widely used in image classification, object detection, and medical image "
         "analysis. In this course, the assignment will use a small CNN to classify images "
         "from a subset of CIFAR-10."),
    ]
)

make_pdf(
    "ISWE411L", "M3-recurrent-networks-and-lstm.pdf",
    "Module 3: Recurrent Neural Networks and LSTMs",
    [
        ("Sequential Data",
         "Recurrent Neural Networks (RNNs) are designed for sequential data such as text, "
         "speech, or time series. Unlike feedforward networks, an RNN maintains a hidden "
         "state that is updated at each time step, allowing information from earlier in the "
         "sequence to influence later predictions."),
        ("The Vanishing Gradient Problem",
         "Plain RNNs struggle to learn long-range dependencies because gradients can shrink "
         "exponentially as they are propagated back through many time steps, a phenomenon "
         "known as the vanishing gradient problem."),
        ("LSTM Cells",
         "Long Short-Term Memory (LSTM) networks address this with a gating mechanism: an "
         "input gate, forget gate, and output gate that control how information flows into, "
         "stays in, and exits the cell state. This lets LSTMs retain relevant information "
         "over much longer sequences than plain RNNs."),
        ("GRUs",
         "Gated Recurrent Units (GRUs) are a simplified alternative to LSTMs with fewer gates "
         "(reset and update gates), often achieving comparable performance with fewer "
         "parameters and faster training."),
        ("Use Cases",
         "RNNs and LSTMs are used for language modeling, machine translation, and time-series "
         "forecasting. In modern practice, many of these tasks have shifted toward Transformer "
         "architectures, which the course covers in a later module."),
    ]
)

make_pdf(
    "ISWE411L", "M4-reinforcement-learning.pdf",
    "Module 4: Reinforcement Learning",
    [
        ("Core Idea",
         "Reinforcement Learning (RL) is a type of learning algorithm where an agent learns "
         "by interacting with an environment. The agent receives rewards or penalties for its "
         "actions and, over many trials, learns a policy that maximizes cumulative reward."),
        ("Key Components",
         "An RL problem is typically framed with a state space, action space, reward function, "
         "and a policy that maps states to actions. The environment is often modeled as a "
         "Markov Decision Process (MDP)."),
        ("Exploration vs Exploitation",
         "A central challenge in RL is balancing exploration (trying new actions to discover "
         "their value) with exploitation (choosing the action currently believed to be best). "
         "Strategies like epsilon-greedy address this trade-off."),
        ("Q-Learning",
         "Q-Learning is a foundational value-based RL algorithm that learns the expected future "
         "reward of taking an action in a given state, without needing a model of the "
         "environment. Deep Q-Networks (DQN) extend this by using a neural network to "
         "approximate the Q-function for large state spaces."),
        ("Example Application",
         "A common classroom example is a self-driving agent in a simulated environment: it "
         "learns to accelerate, stay in lane, and follow traffic rules by interacting with "
         "the environment over thousands of simulated trials, gradually learning to avoid "
         "accidents and penalties."),
    ]
)

make_pdf(
    "ISWE411L", "M5-optimization-and-regularization.pdf",
    "Module 5: Optimization and Regularization",
    [
        ("Gradient Descent Variants",
         "Beyond plain stochastic gradient descent, optimizers like Momentum, RMSProp, and "
         "Adam adapt the learning rate during training. Adam, in particular, combines momentum "
         "with per-parameter adaptive learning rates and is a common default choice."),
        ("Overfitting",
         "Overfitting occurs when a model performs well on training data but poorly on unseen "
         "data, because it has learned noise or overly specific patterns rather than "
         "generalizable structure."),
        ("Dropout",
         "Dropout is a regularization technique that randomly deactivates a fraction of "
         "neurons during each training step, forcing the network to learn redundant, more "
         "robust representations rather than relying on any single neuron."),
        ("Batch Normalization",
         "Batch normalization normalizes layer inputs across a mini-batch, which stabilizes "
         "and speeds up training and can also have a mild regularizing effect."),
        ("Early Stopping",
         "Early stopping monitors validation loss during training and halts training once "
         "validation performance stops improving, preventing the model from continuing to "
         "overfit the training set."),
    ]
)


# ============================================================== MGT2001 ===
# Principles of Management

make_pdf(
    "MGT2001", "U1-introduction-to-management.pdf",
    "Unit 1: Introduction to Management Functions",
    [
        ("Definition of Management",
         "Management is the process of planning, organizing, leading, and controlling "
         "resources -- people, finances, materials, and information -- to achieve "
         "organizational goals efficiently and effectively."),
        ("The Four Functions",
         "The four classic functions of management are planning (setting goals and deciding "
         "how to achieve them), organizing (arranging resources and tasks), leading "
         "(motivating and directing people), and controlling (monitoring performance and "
         "making adjustments)."),
        ("Levels of Management",
         "Organizations typically have three levels of management: top-level (strategic "
         "decisions, e.g. CEOs), middle-level (tactical decisions, e.g. department heads), "
         "and first-line/supervisory (operational decisions, e.g. team leads)."),
        ("Managerial Roles",
         "Mintzberg's framework identifies ten managerial roles grouped into three categories: "
         "interpersonal (figurehead, leader, liaison), informational (monitor, disseminator, "
         "spokesperson), and decisional (entrepreneur, disturbance handler, resource allocator, "
         "negotiator)."),
        ("Exam Note",
         "The first unit exam will focus on the four functions of management and the three "
         "levels of the management hierarchy. Students should be able to give an example of "
         "each function from a real organization."),
    ]
)

make_pdf(
    "MGT2001", "U2-organizational-structure.pdf",
    "Unit 2: Organizational Structure and Design",
    [
        ("What is Organizational Structure",
         "Organizational structure defines how tasks are divided, grouped, and coordinated "
         "within a company. It determines reporting relationships, spans of control, and how "
         "information flows through the organization."),
        ("Functional Structure",
         "In a functional structure, employees are grouped by specialty -- such as marketing, "
         "finance, and operations -- each under its own department head. This promotes "
         "efficiency within specialties but can create silos between departments."),
        ("Divisional Structure",
         "A divisional structure groups employees around products, markets, or geographic "
         "regions, with each division operating somewhat independently. This improves "
         "responsiveness to specific markets but can duplicate resources across divisions."),
        ("Matrix Structure",
         "A matrix structure combines functional and divisional structures, with employees "
         "reporting to both a functional manager and a project or product manager. This "
         "increases flexibility but can create conflicting priorities and dual reporting "
         "confusion."),
        ("Span of Control",
         "Span of control refers to the number of subordinates a manager directly supervises. "
         "A wide span of control leads to flatter organizations, while a narrow span leads to "
         "taller, more hierarchical organizations."),
    ]
)

make_pdf(
    "MGT2001", "U3-leadership-and-motivation.pdf",
    "Unit 3: Leadership Styles and Motivation Theories",
    [
        ("Leadership Styles",
         "Common leadership styles include autocratic (leader makes decisions unilaterally), "
         "democratic (leader involves the team in decision-making), and laissez-faire (leader "
         "gives the team significant autonomy). Effective leaders often adapt their style to "
         "the situation and the maturity of the team."),
        ("Maslow's Hierarchy of Needs",
         "Maslow's hierarchy proposes five levels of human needs -- physiological, safety, "
         "social, esteem, and self-actualization -- arranged in a pyramid. The theory suggests "
         "people are motivated to satisfy lower-level needs before higher-level ones become "
         "primary motivators."),
        ("Herzberg's Two-Factor Theory",
         "Herzberg distinguished between hygiene factors (e.g. salary, working conditions), "
         "which prevent dissatisfaction but don't create motivation on their own, and "
         "motivators (e.g. recognition, achievement, growth), which actively drive job "
         "satisfaction and performance."),
        ("McGregor's Theory X and Theory Y",
         "Theory X assumes employees are inherently unmotivated and need close supervision, "
         "while Theory Y assumes employees are self-motivated and thrive with autonomy and "
         "trust. A manager's assumptions here shape their leadership approach."),
        ("Situational Leadership",
         "Situational leadership theory argues there is no single best leadership style; "
         "instead, effective leaders adjust their approach based on the competence and "
         "commitment level of each team member for a given task."),
    ]
)

make_pdf(
    "MGT2001", "U4-strategic-planning.pdf",
    "Unit 4: Strategic Planning and Decision Making",
    [
        ("Strategic vs Operational Planning",
         "Strategic planning sets long-term direction and major goals for an organization "
         "(typically 3-5+ years), while operational planning translates strategy into "
         "day-to-day activities and short-term targets."),
        ("SWOT Analysis",
         "SWOT analysis evaluates an organization's internal Strengths and Weaknesses "
         "alongside external Opportunities and Threats, helping managers identify strategic "
         "priorities and risks."),
        ("Porter's Five Forces",
         "Michael Porter's Five Forces framework analyzes industry competitiveness through: "
         "threat of new entrants, bargaining power of suppliers, bargaining power of buyers, "
         "threat of substitute products, and rivalry among existing competitors."),
        ("Decision-Making Models",
         "The rational decision-making model involves defining the problem, identifying "
         "criteria, generating alternatives, evaluating them, and selecting the best option. "
         "In practice, managers often use 'bounded rationality' -- satisficing with a good "
         "enough option rather than an exhaustively optimal one, due to time and information "
         "constraints."),
        ("Exam Note",
         "The strategic planning unit exam includes a case study requiring students to conduct "
         "a SWOT analysis and recommend a strategic direction for a fictional company."),
    ]
)

make_pdf(
    "MGT2001", "U5-human-resource-management.pdf",
    "Unit 5: Human Resource Management Basics",
    [
        ("HRM Overview",
         "Human Resource Management (HRM) covers the processes an organization uses to "
         "recruit, develop, motivate, and retain employees, aligning workforce capability "
         "with organizational goals."),
        ("Recruitment and Selection",
         "Recruitment involves attracting a pool of qualified candidates, while selection "
         "involves choosing the best-fit candidate through tools such as interviews, "
         "assessments, and reference checks."),
        ("Training and Development",
         "Training focuses on building skills needed for a current role, while development "
         "focuses on longer-term growth and preparing employees for future responsibilities, "
         "often through mentorship, courses, or stretch assignments."),
        ("Performance Appraisal",
         "Performance appraisal systems formally evaluate employee performance against set "
         "objectives, commonly using methods such as 360-degree feedback, management by "
         "objectives (MBO), or graphic rating scales."),
        ("Compensation and Benefits",
         "Compensation includes direct pay (salary, bonuses) and indirect benefits (health "
         "insurance, retirement plans, paid leave). A well-designed compensation strategy "
         "supports both employee retention and internal equity."),
    ]
)

print("\nAll sample course PDFs generated.")
